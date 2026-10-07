from datetime import UTC, datetime

import pytest

from app.application.reminders.actions import HandleReminderActionUseCase
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.gateways import ReminderAppointment, ReminderPatient
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.fake_appointment_gateway import FakeReminderAppointmentGateway

PHONE = PhoneNumber("+5491112345678")
NOW = datetime(2026, 10, 1, tzinfo=UTC)


class Reminders:
    def __init__(self, reminder=None, review_sent=False):
        self.reminder, self.review_sent = reminder, review_sent
        self.lookups = []

    async def find_sent_for_inbound_action(self, appointment_id, recipient_phone, allowed_kinds):
        self.lookups.append((appointment_id, recipient_phone, frozenset(allowed_kinds)))
        return self.reminder

    async def has_sent_review_request_for_recipient(self, phone):
        return self.review_sent


class Patients:
    def __init__(self, patient):
        self.patient = patient

    async def get_reminder_patient(self, patient_id):
        return self.patient


class Contacts:
    def __init__(self, marked=True):
        self.marked = marked
        self.calls = []

    async def mark_review_opt_out(self, phone, opted_out_at):
        self.calls.append((phone, opted_out_at))
        return self.marked


def reminder(kind="confirm_day_before", patient_id="patient-1"):
    return AppointmentReminder("r-1", "appointment-1", patient_id, kind, "sent", NOW, str(PHONE))


def use_case(reminder_row=None, appointment=None, patient=None, *, review_sent=False, marked=True):
    appointments = FakeReminderAppointmentGateway([appointment] if appointment else [])
    contacts = Contacts(marked)
    return (
        HandleReminderActionUseCase(
            Reminders(reminder_row, review_sent),
            appointments,
            Patients(patient),
            contacts,
            now=lambda: NOW,
        ),
        appointments,
        contacts,
    )


def current(state="active", patient_id="patient-1"):
    return ReminderAppointment("appointment-1", patient_id, NOW, "1", state, state)


def patient(patient_id="patient-1", mobile=PHONE):
    return ReminderPatient(patient_id, mobile, "Paciente")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current_appointment,current_patient",
    [
        (None, patient()),
        (current(patient_id="other"), patient()),
        (current(), patient("other")),
        (current(), patient(mobile=PhoneNumber("+5491199999999"))),
        *((current(state), patient()) for state in ("cancelled", "no_show", "attended", "unknown")),
    ],
)
async def test_appointment_actions_fail_closed_on_missing_mismatched_or_terminal_ownership(
    current_appointment, current_patient
):
    handler, appointments, _ = use_case(reminder(), current_appointment, current_patient)

    result = await handler.handle("REMINDER_CONFIRM:appointment-1", PHONE)

    assert result.handled and result.stale
    assert appointments.patient_whatsapp_confirmation_calls == []


@pytest.mark.asyncio
async def test_confirm_active_uses_the_patient_whatsapp_confirmation_operation():
    handler, appointments, _ = use_case(reminder(), current(), patient())

    result = await handler.handle("REMINDER_CONFIRM:appointment-1", PHONE)

    assert result.outcome == "confirmed"
    assert appointments.patient_whatsapp_confirmation_calls == ["appointment-1"]


@pytest.mark.asyncio
async def test_confirmed_and_location_are_idempotent_or_deferred_to_the_native_location_node():
    handler, appointments, _ = use_case(reminder(), current("confirmed"), patient())

    confirmed = await handler.handle("REMINDER_CONFIRM:appointment-1", PHONE)
    location = await handler.handle("REMINDER_LOCATION:appointment-1", PHONE)

    assert confirmed.outcome == "already_confirmed"
    assert location.location_requested
    assert appointments.patient_whatsapp_confirmation_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["active", "confirmed"])
async def test_reschedule_for_an_owned_active_or_confirmed_appointment_requests_the_flow(state):
    handler, appointments, _ = use_case(
        reminder("confirm_or_location_same_day"), current(state), patient()
    )

    result = await handler.handle("REMINDER_RESCHEDULE:appointment-1", PHONE)

    assert result.handled and not result.stale
    assert result.outcome == "reschedule_requested"
    assert result.reschedule_requested
    assert result.appointment_id == "appointment-1"
    assert result.patient == patient()
    assert appointments.patient_whatsapp_confirmation_calls == []


@pytest.mark.asyncio
async def test_reschedule_looks_up_only_the_two_appointment_reminder_kinds():
    reminders = Reminders(reminder())
    handler = HandleReminderActionUseCase(
        reminders,
        FakeReminderAppointmentGateway([current()]),
        Patients(patient()),
        Contacts(),
        now=lambda: NOW,
    )

    await handler.handle("REMINDER_RESCHEDULE:appointment-1", PHONE)

    assert reminders.lookups == [
        (
            "appointment-1",
            PHONE,
            frozenset({"confirm_day_before", "confirm_or_location_same_day"}),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reminder_row,current_appointment,current_patient",
    [
        (None, current(), patient()),
        (reminder(), None, patient()),
        (reminder(), current(patient_id="other"), patient()),
        (reminder(), current(), patient("other")),
        (reminder(), current(), patient(mobile=PhoneNumber("+5491199999999"))),
        *((reminder(), current(state), patient()) for state in ("cancelled", "no_show")),
        (reminder(), current("attended"), patient()),
    ],
)
async def test_reschedule_fails_closed_on_missing_mismatched_or_terminal_ownership(
    reminder_row, current_appointment, current_patient
):
    handler, _, _ = use_case(reminder_row, current_appointment, current_patient)

    result = await handler.handle("REMINDER_RESCHEDULE:appointment-1", PHONE)

    assert result.handled and result.stale
    assert not result.reschedule_requested
    assert result.appointment_id is None and result.patient is None


@pytest.mark.asyncio
async def test_review_opt_out_requires_sent_review_and_existing_contact_then_is_idempotent():
    handler, _, contacts = use_case(review_sent=True)

    first = await handler.handle("REMINDER_REVIEW_OPTOUT", PHONE)
    second = await handler.handle("REMINDER_REVIEW_OPTOUT", PHONE)

    assert first.outcome == second.outcome == "review_opted_out"
    assert contacts.calls == [(PHONE, NOW), (PHONE, NOW)]


@pytest.mark.asyncio
@pytest.mark.parametrize("review_sent,marked", [(False, True), (True, False)])
async def test_review_opt_out_fails_closed_without_sent_request_or_contact(review_sent, marked):
    handler, _, contacts = use_case(review_sent=review_sent, marked=marked)

    result = await handler.handle("REMINDER_REVIEW_OPTOUT", PHONE)

    assert result.stale
    assert contacts.calls == ([] if not review_sent else [(PHONE, NOW)])


@pytest.mark.asyncio
async def test_unknown_payload_has_no_external_calls():
    handler, appointments, contacts = use_case(reminder(), current(), patient())

    result = await handler.handle("REMINDER_CONFIRM:", PHONE)

    assert not result.handled
    assert appointments.patient_whatsapp_confirmation_calls == []
    assert contacts.calls == []
