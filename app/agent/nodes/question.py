from app.agent.handoff_offer import (
    HANDOFF_OFFER_BUTTONS,
    HANDOFF_OFFER_FLAG_KEY,
    HANDOFF_OFFER_KEY,
)
from app.agent.nodes.fallback import OUT_OF_SCOPE_BUTTONS, OUT_OF_SCOPE_MESSAGE
from app.agent.nodes.node_protocol import AgentNode
from app.agent.nodes.payment_admin import PAYMENT_ADMIN_STATIC_MESSAGE
from app.agent.payment_questions import asks_about_payments
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider


def create_question_node(llm_provider: LLMProvider) -> AgentNode:
    """Answers a free-text question with fixed text only.

    Only programmed capabilities (menu operations, location, the clinic FAQ topics, payments
    to Administración, human handoff) may answer a patient. A free question that is none of
    those gets the approved out-of-scope text and its three buttons, never an answer composed
    by the model: ``understand`` may still fill ``pending_answer``, which is dropped here and
    only read as a signal that the patient asked about payments (a fixed Administración
    redirect). The operational stage is left untouched so an appointment can resume on the
    next turn.
    """

    del llm_provider  # kept for the node-factory signature: no text is LLM-generated here.

    async def node(state: AgentState) -> dict[str, object]:
        collected_data = dict(state["collected_data"])
        pending_answer = collected_data.pop("pending_answer", None)
        collected_data.pop(HANDOFF_OFFER_FLAG_KEY, None)
        if asks_about_payments(state["user_message"]) or (
            isinstance(pending_answer, str) and asks_about_payments(pending_answer)
        ):
            collected_data[HANDOFF_OFFER_KEY] = True
            return {
                "response_text": PAYMENT_ADMIN_STATIC_MESSAGE,
                "response_buttons": HANDOFF_OFFER_BUTTONS,
                "requires_handoff": False,
                "collected_data": collected_data,
            }
        return {
            "response_text": OUT_OF_SCOPE_MESSAGE,
            "response_buttons": OUT_OF_SCOPE_BUTTONS,
            "requires_handoff": False,
            "collected_data": collected_data,
        }

    return node
