"""Deterministic handler for appointment-reminder interactive callbacks."""

from app.agent.nodes.location import clinic_location_reply
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.reminders.actions import HandleReminderActionUseCase
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId

_SAFE_STALE_TEXT = "Este recordatorio ya no está disponible."


def _stale_reply() -> dict[str, object]:
    return {
        "response_text": _SAFE_STALE_TEXT,
        "response_buttons": None,
        "response_image_url": None,
        "response_location": None,
        "requires_handoff": False,
    }


def create_reminder_action_node(
    reminder_actions: HandleReminderActionUseCase | None,
    conversations: ConversationRepository | None,
    contacts: ContactRepository | None,
) -> AgentNode:
    """Resolve the inbound phone and handle a reminder callback fail-closed.

    Reminder payloads are machine actions, never conversational input. The
    use case owns authorization and mutation; this node only resolves the
    sender from the durable conversation/contact relationship and renders its
    deterministic result.
    """

    async def node(state: AgentState) -> dict[str, object]:
        payload = state["button_payload"]
        if payload is None or reminder_actions is None or conversations is None or contacts is None:
            return _stale_reply()
        try:
            conversation = await conversations.get_by_id(ConversationId(state["conversation_id"]))
            if conversation is None:
                return _stale_reply()
            contact = await contacts.get_by_id(conversation.contact_id)
            if contact is None:
                return _stale_reply()
            result = await reminder_actions.handle(payload, contact.phone)
        except Exception:
            # A repository/use-case outage must not let a machine callback
            # fall through to conversational routing or mutate via a retry.
            return _stale_reply()
        if not result.handled or result.stale:
            return _stale_reply()
        if result.location_requested:
            return clinic_location_reply()
        return {
            "response_text": result.text,
            "response_buttons": list(result.buttons) or None,
            "response_image_url": None,
            "response_location": None,
            "requires_handoff": False,
        }

    return node
