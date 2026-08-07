import pytest

from app.domain.repositories.gateways import HumanHandoffGateway
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.chatwoot.fake_chatwoot_gateway import FakeChatwootGateway
from tests.fixtures.gateways import make_chatwoot_gateway


@pytest.mark.asyncio
async def test_request_handoff_records_conversation_id_and_reason():
    gateway = make_chatwoot_gateway()
    conversation_id = ConversationId("conv-1")

    await gateway.request_handoff(conversation_id, "patient requested a human")

    assert gateway.handoff_requests == [(conversation_id, "patient requested a human")]


@pytest.mark.asyncio
async def test_request_handoff_accumulates_multiple_requests():
    gateway = make_chatwoot_gateway()

    await gateway.request_handoff(ConversationId("conv-1"), "reason-a")
    await gateway.request_handoff(ConversationId("conv-2"), "reason-b")

    assert len(gateway.handoff_requests) == 2


def test_fake_chatwoot_gateway_satisfies_human_handoff_gateway_protocol():
    assert isinstance(FakeChatwootGateway(), HumanHandoffGateway)
