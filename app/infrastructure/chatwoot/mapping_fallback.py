import logging

from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.domain.repositories.chatwoot_gateway import ChatwootGateway
from app.domain.repositories.chatwoot_mapping_repository import ChatwootMappingRepository

logger = logging.getLogger(__name__)


class ChatwootContactMappingFallback:
    """`ChatwootMappingRepository` decorator that serves Chatwoot
    conversations with no stored mapping (for example ones created before
    the mappings table was cleared) by asking Chatwoot for the
    conversation's contact.

    The fallback mapping is TRANSIENT and never saved: the table's primary
    key is `conversation_id` (`ycloud-{phone}`) and the patient usually
    already has a newer mapping, so persisting it would violate that key.
    Gateway failures return `None` (logged), never raise.
    """

    def __init__(self, inner: ChatwootMappingRepository, gateway: ChatwootGateway) -> None:
        self._inner = inner
        self._gateway = gateway

    async def save(self, mapping: ChatwootConversationMapping) -> None:
        await self._inner.save(mapping)

    async def get_by_conversation_id(
        self, conversation_id: str
    ) -> ChatwootConversationMapping | None:
        return await self._inner.get_by_conversation_id(conversation_id)

    async def get_by_chatwoot_conversation_id(
        self, chatwoot_conversation_id: str
    ) -> ChatwootConversationMapping | None:
        stored = await self._inner.get_by_chatwoot_conversation_id(chatwoot_conversation_id)
        if stored is not None:
            return stored
        try:
            contact = await self._gateway.find_conversation_contact(chatwoot_conversation_id)
        except Exception:
            logger.warning(
                "chatwoot.mapping_fallback_lookup_failed chatwoot_conversation_id=%s",
                chatwoot_conversation_id,
                exc_info=True,
            )
            return None
        if contact is None:
            return None
        contact_id, phone = contact
        return ChatwootConversationMapping(
            conversation_id=f"ycloud-{phone}",
            chatwoot_contact_id=contact_id,
            chatwoot_conversation_id=chatwoot_conversation_id,
        )
