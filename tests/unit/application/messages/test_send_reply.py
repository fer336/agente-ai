import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.application.messages.send_reply import SendReplyUseCase
from app.domain.repositories.sent_message_repository import SentMessageRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.location_request import LocationRequest
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_sent_message_repository import FakeSentMessageRepository
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.gateways import make_mirror_to_chatwoot_use_case

_CONVERSATION_ID = ConversationId("conv-1")


def _make_use_case(
    messaging_gateway: FakeYCloudMessagingGateway,
    sent_messages: FakeSentMessageRepository | None = None,
    mirror_to_chatwoot=None,
) -> tuple[SendReplyUseCase, FakeSentMessageRepository]:
    sent_messages = sent_messages or FakeSentMessageRepository()

    @asynccontextmanager
    async def provider() -> AsyncIterator[SentMessageRepository]:
        yield sent_messages

    return SendReplyUseCase(messaging_gateway, provider, mirror_to_chatwoot), sent_messages


@pytest.mark.asyncio
async def test_send_reply_sends_text_through_messaging_gateway():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
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
    use_case, _ = _make_use_case(messaging_gateway)

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491199887766"),
        text="Recordatorio: tu cita es mañana a las 10hs",
    )

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491199887766"), "Recordatorio: tu cita es mañana a las 10hs")
    ]


@pytest.mark.asyncio
async def test_send_reply_sends_interactive_buttons_when_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)
    buttons = [
        InteractiveButton(id="CONFIRM_APPOINTMENT", title="✅ Confirmar"),
        InteractiveButton(id="REJECT_APPOINTMENT", title="❌ Cancelar"),
    ]

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
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
    use_case, _ = _make_use_case(messaging_gateway)
    buttons = [InteractiveButton(id="MENU_APPOINTMENT", title="Turnos")]

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
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
    use_case, _ = _make_use_case(messaging_gateway)
    flow = FlowRequest(
        flow_id="flow-1",
        flow_screen_id="VERIFICACION",
        flow_cta="Completar",
        flow_token="ycloud-+5491122334455",
    )

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
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
    use_case, _ = _make_use_case(messaging_gateway)
    flow = FlowRequest(
        flow_id="flow-1", flow_screen_id="VERIFICACION", flow_cta="Completar", flow_token="tok"
    )
    buttons = [InteractiveButton(id="x", title="X")]

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="Hola",
        buttons=buttons,
        flow=flow,
    )

    assert messaging_gateway.sent_flows == [(PhoneNumber("+5491122334455"), "Hola", flow)]
    assert messaging_gateway.sent_buttons == []


@pytest.mark.asyncio
async def test_send_reply_sends_a_location_when_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)
    location = LocationRequest(
        latitude=-34.437762, longitude=-58.7917857, name="Smiling Pilar"
    )

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="",
        location=location,
    )

    assert messaging_gateway.sent_locations == [(PhoneNumber("+5491122334455"), location)]
    assert messaging_gateway.sent_messages == []
    assert messaging_gateway.sent_buttons == []


@pytest.mark.asyncio
async def test_send_reply_prefers_location_over_buttons_when_both_are_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)
    location = LocationRequest(latitude=1.0, longitude=2.0, name="Smiling Pilar")
    buttons = [InteractiveButton(id="x", title="X")]

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="Hola",
        buttons=buttons,
        location=location,
    )

    assert messaging_gateway.sent_locations == [(PhoneNumber("+5491122334455"), location)]
    assert messaging_gateway.sent_buttons == []


@pytest.mark.asyncio
async def test_send_reply_sends_a_list_message_when_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)
    list_message = ListMessage(
        button_label="Elegí una opción",
        rows=[ListRow(id="MENU_CREATE", title="Agendar una cita")],
    )

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="¿En qué te puedo ayudar?",
        list_message=list_message,
    )

    assert messaging_gateway.sent_lists == [
        (PhoneNumber("+5491122334455"), "¿En qué te puedo ayudar?", list_message)
    ]
    assert messaging_gateway.sent_messages == []
    assert messaging_gateway.sent_buttons == []


@pytest.mark.asyncio
async def test_send_reply_prefers_list_message_over_buttons_when_both_are_given():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)
    list_message = ListMessage(button_label="Opciones", rows=[ListRow(id="A", title="A")])
    buttons = [InteractiveButton(id="x", title="X")]

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="Hola",
        buttons=buttons,
        list_message=list_message,
    )

    assert messaging_gateway.sent_lists == [
        (PhoneNumber("+5491122334455"), "Hola", list_message)
    ]
    assert messaging_gateway.sent_buttons == []


@pytest.mark.asyncio
async def test_send_reply_sends_plain_text_when_buttons_is_an_empty_list():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="Turno confirmado",
        buttons=[],
    )

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Turno confirmado")
    ]
    assert messaging_gateway.sent_buttons == []


@pytest.mark.asyncio
async def test_send_reply_returns_the_external_message_id():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, _ = _make_use_case(messaging_gateway)

    external_id = await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="Hola",
    )

    assert external_id == "fake-msg-1"


@pytest.mark.asyncio
async def test_send_reply_correlates_the_external_message_id_to_the_conversation():
    # This is what lets a later async `whatsapp.message.updated` delivery
    # failure be attributed back to a conversation/patient instead of
    # vanishing silently.
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case, sent_messages = _make_use_case(messaging_gateway)

    external_id = await use_case.execute(
        conversation_id=ConversationId("conv-42"),
        to=PhoneNumber("+5491122334455"),
        text="Hola",
    )

    stored = await sent_messages.get_by_id(external_id)
    assert stored is not None
    assert stored.conversation_id == "conv-42"


@pytest.mark.asyncio
async def test_send_reply_mirrors_the_text_reply_to_chatwoot():
    messaging_gateway = FakeYCloudMessagingGateway()
    chatwoot_gateway = FakeChatwootGateway()
    mirror_to_chatwoot = make_mirror_to_chatwoot_use_case(chatwoot_gateway)
    use_case, _ = _make_use_case(messaging_gateway, mirror_to_chatwoot=mirror_to_chatwoot)

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="Tu turno fue confirmado",
    )
    await asyncio.sleep(0.05)  # let the fire-and-forget mirror task run

    assert len(chatwoot_gateway.sent_outgoing) == 1
    assert chatwoot_gateway.sent_outgoing[0][1] == "Tu turno fue confirmado"


@pytest.mark.asyncio
async def test_send_reply_skips_the_mirror_for_blank_text():
    messaging_gateway = FakeYCloudMessagingGateway()
    chatwoot_gateway = FakeChatwootGateway()
    mirror_to_chatwoot = make_mirror_to_chatwoot_use_case(chatwoot_gateway)
    use_case, _ = _make_use_case(messaging_gateway, mirror_to_chatwoot=mirror_to_chatwoot)

    await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="",
        location=LocationRequest(latitude=1.0, longitude=2.0, name="Smiling Pilar"),
    )
    await asyncio.sleep(0.05)

    assert chatwoot_gateway.sent_outgoing == []


@pytest.mark.asyncio
async def test_send_reply_still_returns_the_external_id_when_chatwoot_mirror_fails():
    # Regla de oro: a broken Chatwoot mirror must never affect the real
    # WhatsApp reply the patient already received.
    messaging_gateway = FakeYCloudMessagingGateway()
    mirror_to_chatwoot = make_mirror_to_chatwoot_use_case(FakeChatwootGateway(fail=True))
    use_case, _ = _make_use_case(messaging_gateway, mirror_to_chatwoot=mirror_to_chatwoot)

    external_id = await use_case.execute(
        conversation_id=_CONVERSATION_ID,
        to=PhoneNumber("+5491122334455"),
        text="Tu turno fue confirmado",
    )
    await asyncio.sleep(0.05)

    assert external_id == "fake-msg-1"
