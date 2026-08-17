import pytest

from app.domain.repositories.gateways import HumanHandoffGateway
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from tests.fixtures.gateways import make_ycloud_handoff_gateway


@pytest.mark.asyncio
async def test_request_handoff_records_conversation_id_and_reason():
    gateway = make_ycloud_handoff_gateway()
    conversation_id = ConversationId("ycloud-+5491122334455")

    await gateway.request_handoff(conversation_id, "patient requested a human")

    assert gateway.handoff_requests == [(conversation_id, "patient requested a human")]


@pytest.mark.asyncio
async def test_request_handoff_accumulates_multiple_requests():
    gateway = make_ycloud_handoff_gateway()

    await gateway.request_handoff(ConversationId("ycloud-+5491122334455"), "reason-a")
    await gateway.request_handoff(ConversationId("ycloud-+5491100000000"), "reason-b")

    assert len(gateway.handoff_requests) == 2


def test_fake_ycloud_handoff_gateway_satisfies_human_handoff_gateway_protocol():
    assert isinstance(FakeYCloudHandoffGateway(), HumanHandoffGateway)
