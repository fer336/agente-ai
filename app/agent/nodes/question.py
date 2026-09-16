from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider

_UNKNOWN_ANSWER = (
    "Ese dato no lo tengo confirmado. Si querés, te comunico con administración para revisarlo."
)


def create_question_node(llm_provider: LLMProvider) -> AgentNode:
    async def node(state: AgentState) -> dict[str, object]:
        """Deliver a genuine informational answer without forcing a menu.

        ``resolve_interaction`` currently obtains the text from ``understand`` and
        stores it as ``pending_answer``. This node intentionally does not mutate the
        operational stage, so an appointment can resume on the next turn. A later
        phase will replace generic LLM knowledge with a dedicated ClinicKnowledge
        repository; until then an absent answer fails closed instead of inventing.
        """

        collected_data = dict(state["collected_data"])
        pending_answer = collected_data.pop("pending_answer", None)
        if isinstance(pending_answer, str) and pending_answer.strip():
            text = pending_answer.strip()
        else:
            text = await generate_or_fallback(
                llm_provider,
                state["conversation_id"],
                "question_unknown_answer",
                {
                    "situacion": (
                        "El paciente hizo una pregunta, pero no tenemos una respuesta "
                        "confirmada para dársela."
                    ),
                    "instruccion": (
                        "Decile con calidez que ese dato no lo tenés confirmado y "
                        "ofrecele pasarlo con administración. Nunca inventes el dato."
                    ),
                },
                _UNKNOWN_ANSWER,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
        return {
            "response_text": text,
            "response_buttons": None,
            "requires_handoff": False,
            "collected_data": collected_data,
        }

    return node
