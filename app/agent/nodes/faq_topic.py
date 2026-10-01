from app.agent.clinic_topics import CLINIC_TOPICS, ClinicTopic, match_clinic_topic, topic_by_id
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_FAQ_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    faq_book_payload,
    faq_option_payload,
)

#: `collected_data` key the router sets with the chosen topic id (one-turn carrier).
FAQ_TOPIC_ID_KEY = "faq_topic_id"


def _topic_buttons(topic: ClinicTopic) -> list[InteractiveButton]:
    # A topic that books a fixed specialty carries its own payload so the router can
    # preselect it; the others start a plain booking.
    book_id = faq_book_payload(topic.id) if topic.book_specialty else OPERATION_CREATE_PAYLOAD
    return [
        InteractiveButton(id=book_id, title="Agendar cita"),
        InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
        InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
    ]


def _option_buttons(topic: ClinicTopic) -> list[InteractiveButton]:
    return [
        InteractiveButton(id=faq_option_payload(topic.id, option), title=f"Opción {option}")
        for option in topic.options
    ]


_SUB_LIST_TEXT = "Estos son los temas que más nos consultan. ¿Sobre cuál querés saber?"

_SUB_LIST = ListMessage(
    button_label="Elegí un tema",
    rows=[ListRow(id=topic.payload, title=topic.title) for topic in CLINIC_TOPICS],
    section_title="Consultas frecuentes",
)


def _resolve_topic(topic_id: object, user_message: str) -> ClinicTopic | None:
    return topic_by_id(topic_id) or match_clinic_topic(user_message)


def create_faq_topic_node(aligners_image_url: str = "") -> AgentNode:
    async def node(state: AgentState) -> dict[str, object]:
        """Answer a frequent clinic topic with its fixed text, never LLM-written.

        The workflow data is left untouched (except the one-turn topic id), so this node
        can interrupt a booking temporarily and the stage resumes on the next turn.
        """

        collected_data = dict(state["collected_data"])
        topic = None
        if state["button_payload"] != MENU_FAQ_PAYLOAD:
            topic = _resolve_topic(
                collected_data.pop(FAQ_TOPIC_ID_KEY, None), state["user_message"]
            )
        if topic is None:
            # The menu tap, or a free question the matcher could not pin to one topic:
            # show the same topic list the menu shows, never an invented answer.
            collected_data.pop(FAQ_TOPIC_ID_KEY, None)
            return {
                "response_text": _SUB_LIST_TEXT,
                "response_list": _SUB_LIST,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": collected_data,
            }
        if topic.options:
            # The options replace the usual trio (3 reply buttons at most) and each one
            # starts the booking. The image carries the prices; without a configured URL
            # the text still goes out with the options.
            image_url = aligners_image_url if topic.image_filename else ""
            return {
                "response_text": topic.text,
                "response_buttons": _option_buttons(topic),
                "response_image_url": image_url or None,
                "requires_handoff": False,
                "collected_data": collected_data,
            }
        return {
            "response_text": topic.text,
            "response_buttons": _topic_buttons(topic),
            "requires_handoff": False,
            "collected_data": collected_data,
        }

    return node
