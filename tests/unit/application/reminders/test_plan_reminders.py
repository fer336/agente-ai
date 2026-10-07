from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.application.reminders.plan_reminders import ReminderSettings, plan_reminders
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.phone_number import PhoneNumber

CLINIC_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
SETTINGS = ReminderSettings(
    clinic_timezone=CLINIC_TZ,
    day_before_time=time(18),
    same_day_offset_hours=3,
    send_window_start=time(9),
    send_window_end=time(20),
    review_time=time(10),
)


def _appointment(*, status: str, start_at: datetime) -> Appointment:
    return Appointment(
        id=AppointmentId("apt-1"),
        patient_id="patient-1",
        status=status,
        slot=AppointmentSlot(
            id="slot-1",
            professional_id="professional-1",
            specialty_id="specialty-1",
            time_range=DateTimeRange(start=start_at, end=start_at + timedelta(hours=1)),
        ),
    )


def _patient() -> Patient:
    return Patient(id="patient-1", full_name="Ada", phone=PhoneNumber("+5491112345678"))


def test_active_appointment_gets_day_before_and_confirmation_same_day_in_utc():
    appointment = _appointment(
        status="active", start_at=datetime(2026, 10, 2, 14, 0, tzinfo=CLINIC_TZ)
    )

    candidates = plan_reminders(
        appointment, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
    )

    assert [(candidate.kind, candidate.due_at) for candidate in candidates] == [
        ("confirm_day_before", datetime(2026, 10, 1, 21, tzinfo=UTC)),
        ("confirm_or_location_same_day", datetime(2026, 10, 2, 14, tzinfo=UTC)),
    ]
    assert candidates[1].template_name == "recordatorio_turno_confirmar"
    assert candidates[0].recipient_phone == "+5491112345678"


def test_confirmed_appointment_uses_location_template_for_same_day():
    appointment = _appointment(
        status="confirmed", start_at=datetime(2026, 10, 2, 14, 0, tzinfo=CLINIC_TZ)
    )

    candidates = plan_reminders(
        appointment, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
    )

    assert candidates[1].template_name == "recordatorio_turno_ubicacion"


def test_same_day_candidate_includes_window_boundaries_and_excludes_outside_them():
    at_opening = _appointment(
        status="active", start_at=datetime(2026, 10, 2, 12, 0, tzinfo=CLINIC_TZ)
    )
    at_closing = _appointment(
        status="active", start_at=datetime(2026, 10, 2, 23, 0, tzinfo=CLINIC_TZ)
    )
    before_opening = _appointment(
        status="active", start_at=datetime(2026, 10, 2, 11, 59, tzinfo=CLINIC_TZ)
    )

    opening_candidates = plan_reminders(
        at_opening, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
    )
    closing_candidates = plan_reminders(
        at_closing, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
    )
    before_opening_candidates = plan_reminders(
        before_opening, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
    )

    assert [candidate.kind for candidate in opening_candidates] == [
        "confirm_day_before", "confirm_or_location_same_day"
    ]
    assert [candidate.kind for candidate in closing_candidates] == [
        "confirm_day_before", "confirm_or_location_same_day"
    ]
    assert [candidate.kind for candidate in before_opening_candidates] == ["confirm_day_before"]


def test_same_day_candidate_does_not_cross_to_the_previous_local_calendar_day():
    appointment = _appointment(
        status="active", start_at=datetime(2026, 10, 2, 2, 0, tzinfo=CLINIC_TZ)
    )

    all_day_send_window = ReminderSettings(
        clinic_timezone=CLINIC_TZ,
        day_before_time=time(18),
        same_day_offset_hours=3,
        send_window_start=time(0),
        send_window_end=time(23, 59),
        review_time=time(10),
    )
    candidates = plan_reminders(
        appointment,
        _patient(),
        datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ),
        all_day_send_window,
    )

    assert [candidate.kind for candidate in candidates] == ["confirm_day_before"]


def test_clinic_local_times_convert_to_utc_at_calendar_boundaries():
    midnight_appointment = _appointment(
        status="active", start_at=datetime(2026, 10, 2, 3, 0, tzinfo=CLINIC_TZ)
    )
    late_appointment = _appointment(
        status="active", start_at=datetime(2026, 10, 2, 23, 0, tzinfo=CLINIC_TZ)
    )

    midnight_candidates = plan_reminders(
        midnight_appointment, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
    )
    late_candidates = plan_reminders(
        late_appointment, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
    )

    assert midnight_candidates[0].due_at == datetime(2026, 10, 1, 21, tzinfo=UTC)
    assert late_candidates[1].due_at == datetime(2026, 10, 2, 23, tzinfo=UTC)


def test_attended_appointment_gets_review_next_day_at_clinic_ten_am():
    appointment = _appointment(
        status="attended", start_at=datetime(2026, 10, 2, 14, 0, tzinfo=CLINIC_TZ)
    )

    candidates = plan_reminders(
        appointment, _patient(), datetime(2026, 10, 2, 15, tzinfo=CLINIC_TZ), SETTINGS
    )

    actual = [
        (candidate.kind, candidate.due_at, candidate.template_name)
        for candidate in candidates
    ]
    assert actual == [
        ("review_request", datetime(2026, 10, 3, 13, tzinfo=UTC), "solicitud_resena_google")
    ]


def test_terminal_or_unknown_statuses_do_not_produce_candidates():
    for status in ("cancelled", "no_show", "other"):
        appointment = _appointment(
            status=status, start_at=datetime(2026, 10, 2, 14, 0, tzinfo=CLINIC_TZ)
        )

        assert plan_reminders(
            appointment, _patient(), datetime(2026, 10, 1, 9, tzinfo=CLINIC_TZ), SETTINGS
        ) == []
