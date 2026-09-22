from typing import Protocol, runtime_checkable

from app.domain.value_objects.phone_number import PhoneNumber


@runtime_checkable
class ChatwootGateway(Protocol):
    """Port to Chatwoot's Application API — the CRM mirror clinic staff
    actually reads/replies from (this session's own brief, no PRD.md
    section number). A thin, faithful wrapper over Chatwoot's REST API —
    never touches our own database; conversation-id correlation across
    turns is the caller's job via `ChatwootMappingRepository`.
    """

    async def find_or_create_contact(self, phone: PhoneNumber, name: str) -> tuple[str, str]:
        """Returns `(contact_id, source_id)`, creating the contact (keyed
        by `identifier` = the canonical phone number) if none exists yet.
        `source_id` is Chatwoot's own per-inbox "session" id for this
        contact — required by `create_conversation`, not obtainable any
        other way once the contact already exists."""
        ...

    async def create_conversation(self, source_id: str, contact_id: str) -> str:
        """Returns a NEW Chatwoot conversation id — no idempotent
        find-or-create exists in Chatwoot's own API, callers must not call
        this more than once per real conversation (see
        `ChatwootMappingRepository`)."""
        ...

    async def post_incoming_message(self, chatwoot_conversation_id: str, text: str) -> None:
        """Mirrors a patient's own message into Chatwoot, attributed to
        the contact."""
        ...

    async def post_outgoing_message(self, chatwoot_conversation_id: str, text: str) -> None:
        """Mirrors the bot's own reply into Chatwoot, attributed to the
        Agent Bot (`sender.type == "agent_bot"`) — never to a human
        agent's identity."""
        ...

    async def assign_administracion(self, chatwoot_conversation_id: str) -> None:
        """Labels the conversation "administracion" (escalated to a
        human) — replaces the conversation's whole label set."""
        ...

    async def assign_bot(self, chatwoot_conversation_id: str) -> None:
        """Labels the conversation "agente" (back under bot control) —
        replaces the conversation's whole label set."""
        ...
