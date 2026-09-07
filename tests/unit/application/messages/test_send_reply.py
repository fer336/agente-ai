import pytest

from app.application.messages.send_reply import SendReplyUseCase
from app.domain.value_objects.flow_request import FlowRequest
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
            None,
        )
    ]
    assert messaging_gateway.sent_messages == []


@pytest.mark.asyncio
async def test_send_reply_forwards_the_image_url_to_the_gateway():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = SendReplyUseCase(messaging_gateway)
    buttons = [InteractiveButton(id="MENU_APPOINTMENT", title="Turnos")]

    await use_case.execute(
        to=PhoneNumber("+5491122334455"),
        text="¡Hola!",
        buttons=buttons,
        image_url="https://example.com/logo.png",
    )

    assert messaging_gateway.sent_buttons == [
        (PhoneNumber("+5491122334455"), "¡Hola!", buttons, "https://example.com/logo.png")
    ]


@pytest.mark.asyncio
async def test_send_reply_sends_a_flow_when_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = SendReplyUseCase(messaging_gateway)
    flow = FlowRequest(
        flow_id="flow-1",
        flow_screen_id="VERIFICACION",
        flow_cta="Completar",
        flow_token="ycloud-+5491122334455",
    )

    await use_case.execute(
        to=PhoneNumber("+5491122334455"),
        text="Verificá tus datos",
        flow=flow,
    )

    assert messaging_gateway.sent_flows == [
        (PhoneNumber("+5491122334455"), "Verificá tus datos", flow)
    ]
    assert messaging_gateway.sent_messages == []
    assert messaging_gateway.sent_buttons == []


@pytest.mark.asyncio
async def test_send_reply_prefers_flow_over_buttons_when_both_are_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = SendReplyUseCase(messaging_gateway)
    flow = FlowRequest(
        flow_id="flow-1", flow_screen_id="VERIFICACION", flow_cta="Completar", flow_token="tok"
    )
    buttons = [InteractiveButton(id="x", title="X")]

    await use_case.execute(
        to=PhoneNumber("+5491122334455"), text="Hola", buttons=buttons, flow=flow
    )

    assert messaging_gateway.sent_flows == [(PhoneNumber("+5491122334455"), "Hola", flow)]
    assert messaging_gateway.sent_buttons == []


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
