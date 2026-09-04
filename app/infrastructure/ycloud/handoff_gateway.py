from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.ycloud.client import YCloudClient

#: The tag a human agent removes in YCloud's Shared Team Inbox to hand a
#: conversation back to the bot (see
#: `app.application.conversations.sync_conversation_mode_from_tag`) — this
#: gateway applies the SAME tag automatically the moment the bot itself
#: escalates, so a human agent immediately sees which threads need them
#: without having to tag them by hand first.
_HUMAN_TAG = "Human"


class YCloudHandoffGateway:
    """`YCloudClient`-based real implementation of the `HumanHandoffGateway` port.

    Tags the contact "Human" via YCloud's contact-tags API (`PATCH
    /v2/contact/contacts/{id}`, confirmed against YCloud's published
    OpenAPI spec) rather than an unconfirmed "conversation labels" endpoint
    — mirrors exactly what a human agent does by hand from the Shared Team
    Inbox, and what
    `app.application.conversations.sync_conversation_mode_from_tag` already
    listens for on the way back. `request_handoff` is a no-op (not an
    error) when the contact can't be resolved by phone — PRD.md §21's
    `conversation.mode = "human"` flip (done separately by the calling
    node, not this gateway) is the durable source of truth; this call is a
    best-effort UX nicety for the human agent's inbox.
    """

    def __init__(self, client: YCloudClient) -> None:
        self._client = client

    async def request_handoff(self, conversation_id: ConversationId, reason: str) -> None:
        phone = str(conversation_id).removeprefix("ycloud-")
        contact = await self._client.find_contact_by_phone(phone)
        if contact is None:
            return
        contact_id = contact.get("id")
        if not contact_id:
            return
        raw_tags = contact.get("tags")
        current_tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
        if _HUMAN_TAG in current_tags:
            return
        await self._client.update_contact_tags(str(contact_id), [*current_tags, _HUMAN_TAG])
