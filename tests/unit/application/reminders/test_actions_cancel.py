import pytest

from app.domain.value_objects.menu_payloads import MENU_MAIN_PAYLOAD, OPERATION_RESCHEDULE_PAYLOAD
from tests.unit.application.reminders.test_actions import (
    PHONE,
    current,
    patient,
    reminder,
    use_case,
)


@pytest.mark.asyncio
async def test_first_cancel_tap_returns_second_confirmation_buttons_without_a_write():
    handler, appointments, _ = use_case(reminder(), current(), patient())

    result = await handler.handle("REMINDER_CANCEL:appointment-1", PHONE)

    assert result.outcome == "cancel_confirmation"
    assert [(button.id, button.title) for button in result.buttons] == [
        ("REMINDER_CANCEL_CONFIRM:appointment-1", "Sí, cancelar"),
        ("REMINDER_CANCEL_KEEP:appointment-1", "No, mantener"),
    ]
    assert appointments.cancellation_calls == []


@pytest.mark.asyncio
async def test_cancel_confirmation_cancels_with_a_deterministic_key_and_offers_next_steps():
    handler, appointments, _ = use_case(reminder(), current("confirmed"), patient())

    result = await handler.handle("REMINDER_CANCEL_CONFIRM:appointment-1", PHONE)

    assert result.outcome == "cancelled"
    assert appointments.cancellation_calls == [("appointment-1", "reminder-cancel:appointment-1")]
    assert [(button.id, button.title) for button in result.buttons] == [
        (OPERATION_RESCHEDULE_PAYLOAD, "Agendar nuevo turno"),
        (MENU_MAIN_PAYLOAD, "Menú principal"),
    ]


@pytest.mark.asyncio
async def test_cancel_keep_does_not_write():
    handler, appointments, _ = use_case(reminder(), current(), patient())

    result = await handler.handle("REMINDER_CANCEL_KEEP:appointment-1", PHONE)

    assert result.outcome == "maintained"
    assert appointments.cancellation_calls == []
