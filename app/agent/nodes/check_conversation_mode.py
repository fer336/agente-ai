from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId


def create_check_conversation_mode_node(
    conversation_repository: ConversationRepository,
) -> AgentNode:
    """Defensive re-check of `conversation.mode` at the top of the graph (PRD.md §29).

    `IngestMessageUseCase` (Etapa 4) already gates on `mode == "human"`
    twice before ever invoking `AgentInvoker.handle()` — once at ingestion,
    once right before the debounce-fired seam call. This node is a third,
    defense-in-depth check matching PRD.md §29's diagram and §23's "YCloud
    no será la única fuente de verdad" — it protects any future caller of
    the graph that doesn't go through that use case. When mode is `human`,
    it leaves `intent`/`response_text` at their initial `None` and sets
    `requires_handoff=True`; the graph's routing treats that exact
    combination as "produce no reply, end the run silently" (see
    `app.agent.graph`'s conditional edge after this node).
    """

    async def node(state: AgentState) -> dict[str, object]:
        conversation = await conversation_repository.get_by_id(
            ConversationId(state["conversation_id"])
        )
        if conversation is not None and conversation.mode == "human":
            return {"requires_handoff": True}
        return {}

    return node
