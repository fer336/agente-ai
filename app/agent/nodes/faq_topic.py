from app.agent.clinic_topics import CLINIC_TOPICS, ClinicTopic, match_clinic_topic, topic_by_id
from app.agent.handoff_offer import HANDOFF_OFFER_BUTTONS, HANDOFF_OFFER_KEY
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_FAQ_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
)

#: `collected_data` key the router sets with the chosen topic id (one-turn carrier).
FAQ_TOPIC_ID_KEY = "faq_topic_id"

_TOPIC_BUTTONS = [
    InteractiveButton(id=OPERATION_CREATE_PAYLOAD, title="Agendar cita"),
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
]

_UNKNOWN_TOPIC_TEXT = (
    "Ese dato no lo tengo confirmado. Si querés, te comunico con administración para revisarlo."
)


_SUB_LIST_TEXT = "Estos son los temas que más nos consultan. ¿Sobre cuál querés saber?"

_SUB_LIST = ListMessage(
    button_label="Elegí un tema",
    rows=[ListRow(id=topic.payload, title=topic.title) for topic in CLINIC_TOPICS],
    section_title="Consultas frecuentes",
)


def _resolve_topic(topic_id: object, user_message: str) -> ClinicTopic | None:
    return topic_by_id(topic_id) or match_clinic_topic(user_message)


def create_faq_topic_node() -> AgentNode:
    async def node(state: AgentState) -> dict[str, object]:
        """Answer a frequent clinic topic with its fixed text, never LLM-written.

        The workflow data is left untouched (except the one-turn topic id), so this node
        can interrupt a booking temporarily and the stage resumes on the next turn.
        """

        collected_data = dict(state["collected_data"])
        if state["button_payload"] == MENU_FAQ_PAYLOAD:
            return {
                "response_text": _SUB_LIST_TEXT,
                "response_list": _SUB_LIST,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": collected_data,
            }
        topic = _resolve_topic(collected_data.pop(FAQ_TOPIC_ID_KEY, None), state["user_message"])
        if topic is None:
            collected_data[HANDOFF_OFFER_KEY] = True
            return {
                "response_text": _UNKNOWN_TOPIC_TEXT,
                "response_buttons": HANDOFF_OFFER_BUTTONS,
                "requires_handoff": False,
                "collected_data": collected_data,
            }
        return {
            "response_text": topic.text,
            "response_buttons": _TOPIC_BUTTONS,
            "requires_handoff": False,
            "collected_data": collected_data,
        }

    return node
