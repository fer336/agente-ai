import pytest

from app.application.handoff.request_human_handoff import RequestHumanHandoffUseCase
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.gateways import make_ycloud_handoff_gateway


@pytest.mark.asyncio
async def test_execute_delegates_to_the_handoff_gateway():
    gateway = make_ycloud_handoff_gateway()
    use_case = RequestHumanHandoffUseCase(gateway)

    await use_case.execute(ConversationId("ycloud-+5491122334455"), "patient requested a human")

    assert gateway.handoff_requests == [
        (ConversationId("ycloud-+5491122334455"), "patient requested a human")
    ]
