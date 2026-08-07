from pydantic import BaseModel

from app.application.messages.inbound_message_dto import InboundMessageDTO
from app.domain.value_objects.phone_number import PhoneNumber


class _ChatwootInbox(BaseModel):
    id: int


class _ChatwootSender(BaseModel):
    phone_number: str | None = None


class _ChatwootConversation(BaseModel):
    id: int


class ChatwootMessageCreatedPayload(BaseModel):
    """Raw shape of a Chatwoot `message_created` outgoing webhook event.

    Mirrors Chatwoot's JSON keys verbatim — the vendor-specific schema is
    confined to this module. Only `InboundMessageDTO` (built via
    `to_inbound_message_dto()`) is allowed to cross into `app/application`.
    """

    event: str
    message_type: str
    private: bool = False
    source_id: str = ""
    content: str = ""
    inbox: _ChatwootInbox
    sender: _ChatwootSender
    conversation: _ChatwootConversation

    def to_inbound_message_dto(self) -> InboundMessageDTO:
        """Build the vendor-neutral DTO for an already-filtered incoming message.

        Callers must only invoke this after confirming the event passed the
        route's `event`/`message_type`/`private`/`inbox.id` filters — this
        method does not re-check them. `sender.phone_number` and `source_id`
        have no silent default: a missing value raises explicitly rather
        than producing a DTO with a fabricated phone number or an empty
        `ExternalMessageId` (which `IngestMessageUseCase.execute()` would
        otherwise reject with its own uncaught `ValueError`).
        """
        if not self.sender.phone_number:
            raise ValueError(
                "Chatwoot payload sender.phone_number is required to build InboundMessageDTO"
            )
        if not self.source_id:
            raise ValueError(
                "Chatwoot payload source_id is required to build InboundMessageDTO"
            )
        return InboundMessageDTO(
            external_message_id=self.source_id,
            chatwoot_conversation_id=str(self.conversation.id),
            from_phone=PhoneNumber(self.sender.phone_number),
            text=self.content,
        )
