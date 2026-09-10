from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.value_objects.location_request import LocationRequest

_CLINIC_NAME = "Smiling Pilar"
_CLINIC_LATITUDE = -34.437762
_CLINIC_LONGITUDE = -58.7917857
_CLINIC_ADDRESS = "Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires"

_LOCATION_KEYWORDS = (
    "ubicacion",
    "ubicación",
    "donde queda",
    "dónde queda",
    "donde quedan",
    "donde estan",
    "dónde están",
    "direccion",
    "dirección",
    "como llego",
    "cómo llego",
    "como llegar",
    "cómo llegar",
)


def asks_for_location(text: str) -> bool:
    lowered = text.casefold()
    return any(keyword in lowered for keyword in _LOCATION_KEYWORDS)


async def location_node(state: AgentState) -> dict[str, object]:
    """Return the clinic's verified native WhatsApp location card.

    Location is deterministic clinic data, so it never comes from the LLM.
    Existing workflow data is left untouched, allowing this node to be used as
    a temporary interruption in the middle of a booking.
    """

    del state
    return {
        "response_text": None,
        "response_buttons": None,
        "response_location": LocationRequest(
            latitude=_CLINIC_LATITUDE,
            longitude=_CLINIC_LONGITUDE,
            name=_CLINIC_NAME,
            address=_CLINIC_ADDRESS,
        ),
        "requires_handoff": False,
    }


create_location_node: AgentNode = location_node
