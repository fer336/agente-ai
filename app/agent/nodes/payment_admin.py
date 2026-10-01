from app.agent.handoff_offer import HANDOFF_OFFER_BUTTONS, HANDOFF_OFFER_KEY
from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider

PAYMENT_ADMIN_INTENT = "payment_admin"

PAYMENT_ADMIN_STATIC_MESSAGE = (
    "Los pagos, anticipos y demás precios se manejan directamente con Administración. "
    "Si querés, te comunico con ellos."
)

_PAYMENT_ADMIN_CONTEXT: dict[str, object] = {
    "situacion": (
        "El paciente preguntó por pagos, anticipos, cuotas, financiación o medios de pago."
    ),
    "instruccion": (
        "Decile con calidez que los pagos, anticipos, cuotas y cualquier otro precio se "
        "manejan directamente con Administración, y ofrecele comunicarlo con ellos. Nunca "
        "inventes montos, medios de pago, cuotas ni condiciones. No saludes. Máximo 3 "
        "oraciones cortas."
    ),
}


def create_payment_admin_node(llm_provider: LLMProvider) -> AgentNode:
    """Answer any payment question by deferring to Administración.

    An information intent: it may interrupt a booking temporarily, so the workflow data
    is left untouched and only the handoff-offer flag is added.
    """

    async def node(state: AgentState) -> dict[str, object]:
        text = await generate_or_fallback(
            llm_provider,
            state["conversation_id"],
            PAYMENT_ADMIN_INTENT,
            dict(_PAYMENT_ADMIN_CONTEXT),
            PAYMENT_ADMIN_STATIC_MESSAGE,
            state["recent_messages"],
            state["contact_memory_summary"],
        )
        return {
            "response_text": text,
            "response_buttons": HANDOFF_OFFER_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**state["collected_data"], HANDOFF_OFFER_KEY: True},
        }

    return node
