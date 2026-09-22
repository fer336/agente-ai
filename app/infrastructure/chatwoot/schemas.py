from pydantic import BaseModel

# `sender.type` values (`"contact"`/`"agent_bot"`/`"user"`) are confirmed
# live against this session's own real Chatwoot instance — see
# `app.infrastructure.chatwoot.client.ChatwootClient`'s own docstring for
# how (3 real test messages, REST responses inspected directly). The
# WEBHOOK payload shape below itself is NOT independently verified against
# a live delivery (this receiver did not exist yet to capture one against —
# see this PR's report) — it follows Chatwoot's public, long-stable webhook
# documentation (https://www.chatwoot.com/docs/product/others/webhooks-events),
# which uses the same nested `sender`/`conversation` resource shapes the
# REST API already confirmed. Confirm once a real webhook delivery has been
# captured in production logs.


class ChatwootWebhookSender(BaseModel):
    id: int = 0
    type: str = ""


class ChatwootWebhookConversation(BaseModel):
    id: int = 0


class ChatwootMessageCreatedEventPayload(BaseModel):
    """Raw shape of a Chatwoot `message_created` webhook event."""

    event: str = ""
    message_type: str = ""
    content: str | None = None
    conversation: ChatwootWebhookConversation = ChatwootWebhookConversation()
    sender: ChatwootWebhookSender = ChatwootWebhookSender()


class ChatwootConversationStatusChangedEventPayload(BaseModel):
    """Raw shape of a Chatwoot `conversation_status_changed` webhook event.

    Unlike `message_created`, this event's payload IS the conversation
    resource itself — `id` is the Chatwoot conversation id directly at the
    top level, not nested under a `conversation` key.
    """

    event: str = ""
    id: int = 0
    status: str = ""
