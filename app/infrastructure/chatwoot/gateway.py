from typing import cast

from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.chatwoot.client import ChatwootClient
from app.infrastructure.chatwoot.exceptions import ChatwootAPIError

#: Label names already created on the real Chatwoot account this session
#: (confirmed via the API, not guessed) — reused as-is rather than
#: creating new ones. "agente" = bot control, "administracion" = escalated
#: to a human. Both are the conversation's ENTIRE label set (Chatwoot's
#: labels API replaces, not appends), so each assignment below is the
#: complete desired state, not a delta.
_BOT_LABEL = "agente"
_ADMINISTRACION_LABEL = "administracion"


class ChatwootConversationGateway:
    """`ChatwootClient`-based real implementation of the `ChatwootGateway`
    port.

    No `traced_call`/`ToolExecution` wrapping here, deliberately (unlike
    `app.infrastructure.ycloud.messaging_gateway.YCloudMessagingGateway`):
    every call site fires this gateway via `asyncio.create_task(...)`,
    detached from the node's own `TraceContext` lifetime (the "Regla de
    oro" — a Chatwoot failure must never affect the patient-facing turn),
    so attributing it to that turn's `NodeExecution`/`ToolExecution` would
    be misleading at best. Failures are only ever logged — same
    best-effort posture `HumanHandoffGateway.request_handoff` already
    takes for the exact same reason.
    """

    def __init__(self, client: ChatwootClient) -> None:
        self._client = client

    async def find_or_create_contact(self, phone: PhoneNumber, name: str) -> tuple[str, str]:
        identifier = str(phone)
        try:
            contact = await self._client.create_contact(identifier, identifier, name)
        except ChatwootAPIError as exc:
            if exc.status_code != 422:
                raise
            # Confirmed live: a duplicate `identifier`/`phone_number`
            # returns 422 WITHOUT the existing contact in the body — a
            # second lookup is the only way to get its id.
            existing = await self._client.find_contact_by_identifier(identifier)
            if existing is None:
                raise
            contact = existing
        contact_inboxes = cast("list[dict[str, object]]", contact["contact_inboxes"])
        return str(contact["id"]), str(contact_inboxes[0]["source_id"])

    async def create_conversation(self, source_id: str, contact_id: str) -> str:
        return await self._client.create_conversation(source_id, contact_id)

    async def post_incoming_message(self, chatwoot_conversation_id: str, text: str) -> None:
        await self._client.create_message(chatwoot_conversation_id, text, "incoming")

    async def post_outgoing_message(self, chatwoot_conversation_id: str, text: str) -> None:
        await self._client.create_message(chatwoot_conversation_id, text, "outgoing")

    async def assign_administracion(self, chatwoot_conversation_id: str) -> None:
        await self._client.set_conversation_labels(
            chatwoot_conversation_id, [_ADMINISTRACION_LABEL]
        )

    async def assign_bot(self, chatwoot_conversation_id: str) -> None:
        await self._client.set_conversation_labels(chatwoot_conversation_id, [_BOT_LABEL])
