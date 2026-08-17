from app.domain.repositories.gateways import HumanHandoffGateway
from app.domain.value_objects.conversation_id import ConversationId


class RequestHumanHandoffUseCase:
    """Coordinates escalating a conversation to a human (PRD.md §21).

    Thin orchestration layer: depends only on the `HumanHandoffGateway` port.
    """

    def __init__(self, gateway: HumanHandoffGateway) -> None:
        self._gateway = gateway

    async def execute(self, conversation_id: ConversationId, reason: str) -> None:
        await self._gateway.request_handoff(conversation_id, reason)
