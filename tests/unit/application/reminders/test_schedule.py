from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.application.reminders.schedule import ReminderSchedulingSettings, schedule_reminders
from app.domain.repositories.gateways import ReminderAppointment, ReminderPatient
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_contact_repository import FakeContactRepository

NOW = datetime(2026, 10, 2, 13, tzinfo=UTC)
TZ = ZoneInfo("America/Argentina/Buenos_Aires")
PHONE = PhoneNumber("+5491112345678")


class ReminderRepository:
    def __init__(self):
        self.rows = {}
        self.cooldown = False

    async def upsert(self, row):
        key = (row.appointment_id, row.kind)
        if any((current.appointment_id, current.kind) == key for current in self.rows.values()):
            return False
        self.rows[row.id] = row
        return True

    async def has_sent_review_request_since(self, patient_id, cutoff):
        return self.cooldown


class ContactPreferences:
    def __init__(self, opted_out=False):
        self.opted_out = opted_out
        self.phones = []

    async def is_review_opted_out(self, phone):
        self.phones.append(phone)
        return self.opted_out


class Appointments:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def list_reminder_appointments_for_date_window(self, start, end):
        self.calls += 1
        return self.rows


class Patients:
    def __init__(self, patient):
        self.patient = patient
        self.calls = 0

    async def get_reminder_patient(self, patient_id):
        self.calls += 1
        return self.patient


def appointment(state="active"):
    return ReminderAppointment(
        "apt-1", "patient-1", datetime(2026, 10, 3, 14, tzinfo=TZ), "1", state, state
    )


def patient():
    return ReminderPatient("patient-1", PHONE, "Ada")


def settings(enabled=True):
    return ReminderSchedulingSettings(
        enabled, {str(PHONE)}, TZ, time(18), 3, time(9), time(20), time(10), 90
    )


@pytest.mark.asyncio
async def test_disabled_or_empty_allowlist_never_calls_dentalink():
    appointments = Appointments([appointment()])
    patients = Patients(patient())
    repository = ReminderRepository()

    assert await schedule_reminders(appointments, patients, repository, NOW, settings(False)) == 0
    assert (
        await schedule_reminders(
            appointments,
            patients,
            repository,
            NOW,
            ReminderSchedulingSettings(
                False, set(), TZ, time(18), 3, time(9), time(20), time(10), 90
            ),
        )
        == 0
    )
    assert appointments.calls == patients.calls == 0


@pytest.mark.asyncio
async def test_scheduling_is_idempotent_and_observes_review_cooldown():
    rows = [
        appointment(),
        ReminderAppointment(
            "apt-2",
            "patient-1",
            datetime(2026, 10, 1, 14, tzinfo=TZ),
            "2",
            "attended",
            "attended",
        ),
    ]
    repository = ReminderRepository()
    appointments = Appointments(rows)
    patients = Patients(patient())

    assert await schedule_reminders(appointments, patients, repository, NOW, settings()) == 3
    assert await schedule_reminders(appointments, patients, repository, NOW, settings()) == 0
    repository.cooldown = True
    assert await schedule_reminders(appointments, patients, repository, NOW, settings()) == 0


@pytest.mark.asyncio
async def test_review_opt_out_suppresses_only_review_requests():
    rows = [
        appointment(),
        ReminderAppointment(
            "apt-2",
            "patient-1",
            datetime(2026, 10, 1, 14, tzinfo=TZ),
            "2",
            "attended",
            "attended",
        ),
    ]
    repository = ReminderRepository()
    preferences = ContactPreferences(opted_out=True)

    assert (
        await schedule_reminders(
            Appointments(rows),
            Patients(patient()),
            repository,
            NOW,
            settings(),
            preferences,
        )
        == 2
    )
    assert {row.kind for row in repository.rows.values()} == {
        "confirm_day_before",
        "confirm_or_location_same_day",
    }
    assert preferences.phones == [PHONE]


@pytest.mark.asyncio
async def test_missing_contact_is_eligible_for_a_review_request():
    repository = ReminderRepository()
    preferences = FakeContactRepository()
    attended = ReminderAppointment(
        "apt-2",
        "patient-1",
        datetime(2026, 10, 1, 14, tzinfo=TZ),
        "2",
        "attended",
        "attended",
    )

    assert (
        await schedule_reminders(
            Appointments([attended]),
            Patients(patient()),
            repository,
            NOW,
            settings(),
            preferences,
        )
        == 1
    )
    assert {row.kind for row in repository.rows.values()} == {"review_request"}
