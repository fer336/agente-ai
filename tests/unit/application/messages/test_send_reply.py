import pytest

from app.application.messages.send_reply import SendReplyUseCase
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.chatwoot.fake_chatwoot_conversation_gateway import (
    FakeChatwootConversationGateway,
)
from app.infrastructure.whatsapp.fake_whatsapp_gateway import FakeWhatsAppGateway


@pytest.mark.asyncio
async def test_both_writes_occur():
    messaging_gateway = FakeWhatsAppGateway()
    chatwoot_gateway = FakeChatwootConversationGateway()
    use_case = SendReplyUseCase(messaging_gateway, chatwoot_gateway)

    await use_case.execute(
        to=PhoneNumber("+5491122334455"),
        chatwoot_conversation_id="100",
        text="Tu turno fue confirmado para el martes",
    )

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Tu turno fue confirmado para el martes")
    ]
    assert chatwoot_gateway.mirrored_messages == [
        ("100", "Tu turno fue confirmado para el martes")
    ]


@pytest.mark.asyncio
async def test_both_writes_occur_with_different_conversation_and_text():
    # TRIANGULATE: a second, distinct conversation/text pair proves the
    # dual-write isn't hardcoded and that both gateways always receive the
    # SAME text (spec's "Both writes occur" scenario: identical text).
    messaging_gateway = FakeWhatsAppGateway()
    chatwoot_gateway = FakeChatwootConversationGateway()
    use_case = SendReplyUseCase(messaging_gateway, chatwoot_gateway)

    await use_case.execute(
        to=PhoneNumber("+5491199887766"),
        chatwoot_conversation_id="777",
        text="Recordatorio: tu cita es mañana a las 10hs",
    )

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491199887766"), "Recordatorio: tu cita es mañana a las 10hs")
    ]
    assert chatwoot_gateway.mirrored_messages == [
        ("777", "Recordatorio: tu cita es mañana a las 10hs")
    ]
