from datetime import UTC, datetime

import pytest

from app.agent.nodes.reminder_action import create_reminder_action_node
from app.application.reminders.actions import ReminderActionResult
from app.domain.entities.contact import Contact
from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import LOCATION_DETAIL_PAYLOAD
from app.domain.value_objects.phone_number import PhoneNumber
from tests.fixtures.agent_state import make_agent_state

_PHONE = PhoneNumber("+5491112345678")
_NOW = datetime(2026, 10, 1, tzinfo=UTC)
_STALE = "Este recordatorio ya no está disponible."


class _Conversations:
    def __init__(self, conversation: Conversation | None) -> None:
        self.conversation = conversation
        self.calls: list[ConversationId] = []

    async def get_by_id(self, conversation_id: ConversationId) -> Conversation | None:
        self.calls.append(conversation_id)
        return self.conversation


class _Contacts:
    def __init__(self, contact: Contact | None) -> None:
        self.contact = contact
        self.calls: list[str] = []

    async def get_by_id(self, contact_id: str) -> Contact | None:
        self.calls.append(contact_id)
        return self.contact


class _Actions:
    def __init__(self, result: ReminderActionResult) -> None:
        self.result = result
        self.calls: list[tuple[str, PhoneNumber]] = []

    async def handle(self, payload: str, inbound_phone: PhoneNumber) -> ReminderActionResult:
        self.calls.append((payload, inbound_phone))
        return self.result


def _conversation() -> Conversation:
    return Conversation(ConversationId("conv-1"), "contact-1", "agent", _NOW)


def _contact() -> Contact:
    return Contact("contact-1", _PHONE, None)


def _confirmed_actions() -> _Actions:
    return _Actions(ReminderActionResult(True, "confirmed", "Tu turno fue confirmado."))


def _stale_result() -> dict[str, object]:
    return {
        "response_text": _STALE,
        "response_buttons": None,
        "response_image_url": None,
        "response_location": None,
        "requires_handoff": False,
    }


@pytest.mark.asyncio
async def test_reminder_action_node_resolves_phone_and_renders_result_buttons() -> None:
    actions = _Actions(
        ReminderActionResult(
            True,
            "cancel_confirmation",
            "¿Querés cancelar tu turno?",
            (InteractiveButton("REMINDER_CANCEL_CONFIRM:apt-1", "Sí, cancelar"),),
        )
    )
    node = create_reminder_action_node(
        actions, _Conversations(_conversation()), _Contacts(_contact())
    )

    result = await node(make_agent_state(button_payload="REMINDER_CANCEL:apt-1"))

    assert actions.calls == [("REMINDER_CANCEL:apt-1", _PHONE)]
    assert result == {
        "response_text": "¿Querés cancelar tu turno?",
        "response_buttons": [InteractiveButton("REMINDER_CANCEL_CONFIRM:apt-1", "Sí, cancelar")],
        "response_image_url": None,
        "response_location": None,
        "requires_handoff": False,
    }


@pytest.mark.asyncio
async def test_reminder_action_node_uses_the_existing_native_location_reply() -> None:
    actions = _Actions(ReminderActionResult(True, "location", location_requested=True))
    node = create_reminder_action_node(
        actions, _Conversations(_conversation()), _Contacts(_contact())
    )

    result = await node(make_agent_state(button_payload="REMINDER_LOCATION:apt-1"))

    assert actions.calls == [("REMINDER_LOCATION:apt-1", _PHONE)]
    assert result["response_text"] is None
    assert result["response_buttons"] is None
    assert result["response_location"] is not None
    assert result["response_location"].latitude == -34.437762


@pytest.mark.asyncio
async def test_reminder_location_tap_sends_the_clinic_image_prompt_when_configured() -> None:
    actions = _Actions(ReminderActionResult(True, "location", location_requested=True))
    node = create_reminder_action_node(
        actions,
        _Conversations(_conversation()),
        _Contacts(_contact()),
        location_image_url="https://example.test/clinic.jpg",
    )

    result = await node(make_agent_state(button_payload="REMINDER_LOCATION:apt-1"))

    assert result["response_image_url"] == "https://example.test/clinic.jpg"
    assert result["response_location"] is None
    assert result["response_text"] is not None
    assert result["response_buttons"] == [
        InteractiveButton(LOCATION_DETAIL_PAYLOAD, "Cómo llegar")
    ]


@pytest.mark.asyncio
async def test_reminder_action_node_fails_closed_without_the_use_case() -> None:
    node = create_reminder_action_node(None, _Conversations(_conversation()), _Contacts(_contact()))

    assert await node(make_agent_state(button_payload="REMINDER_CONFIRM:apt-1")) == _stale_result()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["conversations", "contacts", "conversation", "contact"])
async def test_reminder_action_node_fails_closed_without_dependency_or_resolution(
    missing: str,
) -> None:
    actions = _confirmed_actions()
    conversations = None if missing == "conversations" else _Conversations(
        None if missing == "conversation" else _conversation()
    )
    contacts = None if missing == "contacts" else _Contacts(
        None if missing == "contact" else _contact()
    )
    node = create_reminder_action_node(actions, conversations, contacts)

    assert await node(make_agent_state(button_payload="REMINDER_CONFIRM:apt-1")) == _stale_result()
    assert actions.calls == []


@pytest.mark.asyncio
async def test_reminder_action_node_fails_closed_for_a_malformed_machine_payload() -> None:
    actions = _Actions(ReminderActionResult(False, "not_handled"))
    node = create_reminder_action_node(
        actions, _Conversations(_conversation()), _Contacts(_contact())
    )

    result = await node(make_agent_state(button_payload="REMINDER_CONFIRM:"))

    assert actions.calls == [("REMINDER_CONFIRM:", _PHONE)]
    assert result["response_text"] == _STALE
    assert result["response_buttons"] is None
