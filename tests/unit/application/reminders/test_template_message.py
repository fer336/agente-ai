from datetime import UTC, datetime

import pytest

from app.application.reminders.template_message import build_template_message
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.gateways import (
    ReminderAppointment,
    ReminderPatient,
    TemplateQuickReplyButton,
)
from app.domain.value_objects.phone_number import PhoneNumber

PHONE = PhoneNumber("+5491112345678")
STARTS_AT = datetime(2026, 10, 3, 14, tzinfo=UTC)


def reminder(kind: str) -> AppointmentReminder:
    return AppointmentReminder(
        "reminder-1", "apt-1", "patient-1", kind, "pending", STARTS_AT, str(PHONE)
    )


def appointment(state: str) -> ReminderAppointment:
    return ReminderAppointment("apt-1", "patient-1", STARTS_AT, "1", state, state)


def patient() -> ReminderPatient:
    return ReminderPatient("patient-1", PHONE, "Ada")


def build(kind: str, state: str):
    return build_template_message(
        reminder(kind),
        appointment(state),
        patient(),
        language="es_AR",
        confirmation_template_name="recordatorio_turno_confirmar",
        location_template_name="recordatorio_turno_ubicacion",
        review_template_name="solicitud_resena_google",
        unconfirmed_template_name="recordatorio_turno_sin_confirmar",
    )


@pytest.mark.parametrize(
    ("kind", "state", "template", "body", "payloads"),
    [
        (
            "confirm_day_before",
            "active",
            "recordatorio_turno_confirmar",
            ("Ada", "sábado 3 de octubre", "14:00"),
            ("REMINDER_CONFIRM:apt-1",),
        ),
        (
            "confirm_day_before",
            "confirmed",
            "recordatorio_turno_confirmar",
            ("Ada", "sábado 3 de octubre", "14:00"),
            ("REMINDER_CONFIRM:apt-1",),
        ),
        (
            "confirm_or_location_same_day",
            "confirmed",
            "recordatorio_turno_ubicacion",
            ("Ada", "14:00"),
            ("REMINDER_LOCATION:apt-1",),
        ),
        (
            "confirm_or_location_same_day",
            "active",
            "recordatorio_turno_sin_confirmar",
            ("Ada", "sábado 3 de octubre", "14:00"),
            ("REMINDER_CONFIRM:apt-1", "REMINDER_RESCHEDULE:apt-1"),
        ),
        (
            "review_request",
            "attended",
            "solicitud_resena_google",
            ("Ada",),
            ("REMINDER_REVIEW_OPTOUT",),
        ),
    ],
)
def test_builds_approved_template_for_eligible_reminder(kind, state, template, body, payloads):
    message = build(kind, state)

    assert message is not None
    assert message.name == template
    assert message.body_parameters == body
    assert tuple(button.payload for button in message.quick_reply_buttons) == payloads


def test_builds_configured_template_and_preserves_review_button_index_one():
    message = build_template_message(
        reminder("review_request"),
        appointment("attended"),
        patient(),
        language="es_MX",
        confirmation_template_name="custom-confirm",
        location_template_name="custom-location",
        review_template_name="custom-review",
        unconfirmed_template_name="custom-unconfirmed",
    )

    assert message is not None
    assert message.name == "custom-review"
    assert message.language == "es_MX"
    assert message.quick_reply_buttons == (
        TemplateQuickReplyButton(index=1, payload="REMINDER_REVIEW_OPTOUT"),
    )


def test_unconfirmed_same_day_template_uses_configured_name_and_button_indexes():
    message = build_template_message(
        reminder("confirm_or_location_same_day"),
        appointment("active"),
        patient(),
        language="es_AR",
        confirmation_template_name="custom-confirm",
        location_template_name="custom-location",
        review_template_name="custom-review",
        unconfirmed_template_name="custom-unconfirmed",
    )

    assert message is not None
    assert message.name == "custom-unconfirmed"
    assert message.quick_reply_buttons == (
        TemplateQuickReplyButton(index=0, payload="REMINDER_CONFIRM:apt-1"),
        TemplateQuickReplyButton(index=1, payload="REMINDER_RESCHEDULE:apt-1"),
    )
