from dataclasses import dataclass


@dataclass
class ChatwootConversationMapping:
    """Correlates one of our own conversations to its mirrored Chatwoot
    contact/conversation (this session's own brief, no PRD.md section
    number — see `app.infrastructure.chatwoot.gateway` for the full
    context).

    Exists because Chatwoot's API has no idempotent "find or create
    conversation" endpoint (confirmed against Chatwoot's own docs — only
    a plain, un-idempotent `POST /conversations`) — without tracking the
    returned id ourselves, every mirrored turn would spawn a new Chatwoot
    conversation instead of continuing the same thread.
    """

    conversation_id: str
    chatwoot_contact_id: str
    chatwoot_conversation_id: str
