from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.conversations.set_conversation_input_state import HUMAN as INPUT_STATE_HUMAN
from app.application.conversations.set_conversation_input_state import (
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.application.handoff.request_human_handoff import RequestHumanHandoffUseCase
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import HumanHandoffGateway
from app.domain.value_objects.conversation_id import ConversationId

_HANDOFF_ACK_MESSAGE = (
    "Perfecto. Te comunico con administración de la clínica.\n\n"
    "Podrán continuar la conversación desde este mismo chat."
)


def create_handoff_node(
    handoff_gateway: HumanHandoffGateway,
    conversation_repository: ConversationRepository,
) -> AgentNode:
    """Derives the conversation to administración (PRD.md §21-22).

    Covers both the manual "💬 Administración" selection and PRD.md §22's
    automatic-derivation phrases ("voy a llegar tarde", "necesito hablar con
    una persona", ...) — both reach this node the same way, via
    `resolve_interaction` classifying `intent="handoff"`. The automatic-
    phrase detection lives in the classifier (`FakeLLMProvider`'s handoff
    keywords for now); this node only executes the handoff mechanics
    uniformly once routed here, per PRD.md §22: "No se intentará modificar
    automáticamente un turno porque el paciente indique que llegará tarde.
    Ese caso siempre se deriva" — this node never inspects `appointment_action`
    or attempts any appointment operation, it only escalates.
    """
    request_handoff = RequestHumanHandoffUseCase(handoff_gateway)
    set_conversation_mode = SetConversationModeUseCase(conversation_repository)
    set_conversation_input_state = SetConversationInputStateUseCase(conversation_repository)

    async def node(state: AgentState) -> dict[str, object]:
        conversation_id = ConversationId(state["conversation_id"])
        await request_handoff.execute(conversation_id, reason=state["user_message"])
        await set_conversation_mode.execute(conversation_id, mode="human")
        await set_conversation_input_state.execute(conversation_id, INPUT_STATE_HUMAN)
        return {"response_text": _HANDOFF_ACK_MESSAGE, "requires_handoff": True}

    return node
