from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.value_objects.treatment_catalog import TREATMENT_CATALOG_TEXT


def create_treatment_catalog_node() -> AgentNode:
    """Answers "qué tratamientos/precios tienen" with the static FAQ catalog
    (this session's own brief, see `app.domain.value_objects.
    treatment_catalog`'s own docstring for why it's hardcoded).

    A pure FAQ answer, never a booking step — contrast `specialties.py`'s
    `create_specialties_node`, which actually starts the live Dentalink
    professional-selection flow. This node takes no gateway, never touches
    `SpecialtyGateway`, never writes a booking field into `collected_data`,
    and never advances `collected_data["stage"]` — it simply omits
    `collected_data` from its return, so LangGraph leaves whatever stage
    was already there untouched.
    """

    async def node(state: AgentState) -> dict[str, object]:
        return {
            "response_text": TREATMENT_CATALOG_TEXT,
            "response_buttons": None,
            "response_list": None,
            "requires_handoff": False,
        }

    return node
