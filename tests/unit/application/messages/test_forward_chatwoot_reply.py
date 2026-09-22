import pytest

from app.application.messages.forward_chatwoot_reply import ForwardChatwootReplyUseCase
from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway


@pytest.mark.asyncio
async def test_forwards_the_staff_reply_to_the_mapped_whatsapp_conversation():
    mapping_repository = FakeChatwootMappingRepository()
    await mapping_repository.save(
        ChatwootConversationMapping(
            conversation_id="ycloud-+5491122334455",
            chatwoot_contact_id="1",
            chatwoot_conversation_id="99",
        )
    )
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = ForwardChatwootReplyUseCase(messaging_gateway, mapping_repository)

    await use_case.execute("99", "Hola, te confirmo el turno")

    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Hola, te confirmo el turno")
    ]


@pytest.mark.asyncio
async def test_no_ops_when_no_mapping_exists_for_the_chatwoot_conversation():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = ForwardChatwootReplyUseCase(messaging_gateway, FakeChatwootMappingRepository())

    await use_case.execute("does-not-exist", "Hola")

    assert messaging_gateway.sent_messages == []
