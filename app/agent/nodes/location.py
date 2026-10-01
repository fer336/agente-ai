from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.location_request import LocationRequest
from app.domain.value_objects.menu_payloads import LOCATION_DETAIL_PAYLOAD

_CLINIC_NAME = "Smiling Pilar"
_CLINIC_LATITUDE = -34.437762
_CLINIC_LONGITUDE = -58.7917857
_CLINIC_ADDRESS = "Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires"

#: Caption of the clinic image (WhatsApp allows up to 1024 characters; this stays short).
_IMAGE_CAPTION = (
    "📍 Así llegás a Smiling Pilar: Las Camelias 3324, Oficina 207 (Office Park Norte). "
    "Tocá el botón para abrir la ubicación en el mapa."
)
_HOW_TO_ARRIVE_BUTTON = InteractiveButton(id=LOCATION_DETAIL_PAYLOAD, title="Cómo llegar")

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


def clinic_location_reply() -> dict[str, object]:
    """The clinic's verified native WhatsApp location card, with no text or buttons.

    Location is deterministic clinic data, so it never comes from the LLM: a model
    "retyping" coordinates risks a mangled pin.
    """

    return {
        "response_text": None,
        "response_buttons": None,
        "response_image_url": None,
        "response_location": LocationRequest(
            latitude=_CLINIC_LATITUDE,
            longitude=_CLINIC_LONGITUDE,
            name=_CLINIC_NAME,
            address=_CLINIC_ADDRESS,
        ),
        "requires_handoff": False,
    }


def create_location_node(image_url: str = "") -> AgentNode:
    """Answer a location request.

    A question (free text, the menu row) gets the clinic image with a short caption and
    one "Cómo llegar" button; tapping it returns the native location card. Without a
    configured `image_url` the card is sent right away. Existing workflow data is left
    untouched, so this node works as a temporary interruption in the middle of a booking.
    """

    async def node(state: AgentState) -> dict[str, object]:
        if not image_url or state["button_payload"] == LOCATION_DETAIL_PAYLOAD:
            return clinic_location_reply()
        return {
            "response_text": _IMAGE_CAPTION,
            "response_buttons": [_HOW_TO_ARRIVE_BUTTON],
            "response_image_url": image_url,
            "response_location": None,
            "requires_handoff": False,
        }

    return node


#: Backward-compatible node with no image configured: it sends the native card.
location_node: AgentNode = create_location_node()
