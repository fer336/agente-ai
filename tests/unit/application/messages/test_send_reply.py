import pytest

from app.application.messages.send_reply import SendReplyUseCase
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway


@pytest.mark.asyncio
async def test_send_reply_sends_text_through_messaging_gateway():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = SendReplyUseCase(messaging_gateway)

    await use_case.execute(
        to=PhoneNumber("+5491122334455"),
        text="Tu turno fue confirmado para el martes",
    )

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Tu turno fue confirmado para el martes")
    ]


@pytest.mark.asyncio
async def test_send_reply_sends_the_exact_text_for_a_different_phone_and_message():
    # TRIANGULATE: a second, distinct phone/text pair proves the send isn't
    # hardcoded.
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = SendReplyUseCase(messaging_gateway)

    await use_case.execute(
        to=PhoneNumber("+5491199887766"),
        text="Recordatorio: tu cita es mañana a las 10hs",
    )

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491199887766"), "Recordatorio: tu cita es mañana a las 10hs")
    ]


@pytest.mark.asyncio
async def test_send_reply_sends_interactive_buttons_when_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = SendReplyUseCase(messaging_gateway)
    buttons = [
        InteractiveButton(id="CONFIRM_APPOINTMENT", title="✅ Confirmar"),
        InteractiveButton(id="REJECT_APPOINTMENT", title="❌ Cancelar"),
    ]

    await use_case.execute(
        to=PhoneNumber("+5491122334455"),
        text="¿Confirmás el turno del martes a las 10hs?",
        buttons=buttons,
    )

    assert messaging_gateway.sent_buttons == [
        (
            PhoneNumber("+5491122334455"),
            "¿Confirmás el turno del martes a las 10hs?",
            buttons,
        )
    ]
    assert messaging_gateway.sent_messages == []


@pytest.mark.asyncio
async def test_send_reply_sends_plain_text_when_buttons_is_an_empty_list():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = SendReplyUseCase(messaging_gateway)

    await use_case.execute(
        to=PhoneNumber("+5491122334455"),
        text="Turno confirmado",
        buttons=[],
    )

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Turno confirmado")
    ]
    assert messaging_gateway.sent_buttons == []
