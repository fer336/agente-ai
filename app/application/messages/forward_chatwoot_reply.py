from app.domain.repositories.chatwoot_mapping_repository import ChatwootMappingRepository
from app.domain.repositories.gateways import MessagingGateway
from app.domain.value_objects.phone_number import PhoneNumber


class ForwardChatwootReplyUseCase:
    """Forwards a staff-typed Chatwoot reply to the real WhatsApp
    conversation it mirrors — the "camino de vuelta" (Chatwoot -> WhatsApp)
    counterpart to `MirrorMessageToChatwootUseCase.mirror_outgoing`'s own
    WhatsApp -> Chatwoot direction (this session's own brief, no PRD.md
    section number).

    No-ops (does not raise) when no mapping exists yet for this Chatwoot
    conversation — same "ack-and-drop rather than crash" stance the YCloud
    webhook route already uses for a plausible-but-incomplete payload.
    """

    def __init__(
        self,
        messaging_gateway: MessagingGateway,
        mapping_repository: ChatwootMappingRepository,
    ) -> None:
        self._messaging_gateway = messaging_gateway
        self._mapping_repository = mapping_repository

    async def execute(self, chatwoot_conversation_id: str, text: str) -> None:
        mapping = await self._mapping_repository.get_by_chatwoot_conversation_id(
            chatwoot_conversation_id
        )
        if mapping is None:
            return

        # `conversation_id` IS `ycloud-{phone}` by construction — see
        # `IngestMessageUseCase._resolve_or_create_conversation`'s own
        # docstring for this deliberate, documented encoding convention.
        phone = mapping.conversation_id.removeprefix("ycloud-")
        await self._messaging_gateway.send_text_message(PhoneNumber(phone), text)
