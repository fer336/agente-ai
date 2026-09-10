from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState

_UNKNOWN_ANSWER = (
    "Ese dato no lo tengo confirmado. Si querés, te comunico con administración para revisarlo."
)


async def question_node(state: AgentState) -> dict[str, object]:
    """Deliver a genuine informational answer without forcing a menu.

    ``resolve_interaction`` currently obtains the text from ``understand`` and
    stores it as ``pending_answer``. This node intentionally does not mutate the
    operational stage, so an appointment can resume on the next turn. A later
    phase will replace generic LLM knowledge with a dedicated ClinicKnowledge
    repository; until then an absent answer fails closed instead of inventing.
    """

    collected_data = dict(state["collected_data"])
    pending_answer = collected_data.pop("pending_answer", None)
    text = (
        pending_answer.strip()
        if isinstance(pending_answer, str) and pending_answer.strip()
        else _UNKNOWN_ANSWER
    )
    return {
        "response_text": text,
        "response_buttons": None,
        "requires_handoff": False,
        "collected_data": collected_data,
    }


create_question_node: AgentNode = question_node
