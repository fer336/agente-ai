import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.domain.repositories.chatwoot_gateway import ChatwootGateway
from app.domain.repositories.chatwoot_mapping_repository import ChatwootMappingRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber

logger = logging.getLogger(__name__)

#: Same shape as `SendReplyUseCase`'s own `SentMessageRepositoriesProvider`
#: — an async-context-manager factory, so a fresh session is opened per
#: call rather than held open for this use case's lifetime.
ChatwootMappingRepositoriesProvider = Callable[
    [], AbstractAsyncContextManager[ChatwootMappingRepository]
]


class MirrorMessageToChatwootUseCase:
    """Mirrors WhatsApp traffic into Chatwoot so clinic staff can read and
    reply to patients from Chatwoot's own inbox (this session's own brief,
    no PRD.md section number — see `app.infrastructure.chatwoot.gateway`
    for the full context).

    Regla de oro, no negociable: Chatwoot is a MIRROR, never the source of
    truth for a patient's real WhatsApp conversation. Every public method
    here swallows every exception and only logs a warning — never raises,
    never lets a Chatwoot outage or bug delay or break the real reply a
    patient is waiting for. Callers are expected to fire these via
    `asyncio.create_task(...)` (fire-and-forget) rather than `await`ing
    them inline on the hot path, so even a slow-but-successful Chatwoot
    call adds zero latency to the patient-facing turn — the "never raises"
    guarantee here is a second, independent layer of protection on top of
    that, not a substitute for it.
    """

    def __init__(
        self,
        chatwoot_gateway: ChatwootGateway,
        mapping_repositories_provider: ChatwootMappingRepositoriesProvider,
    ) -> None:
        self._chatwoot_gateway = chatwoot_gateway
        self._mapping_repositories_provider = mapping_repositories_provider

    async def mirror_incoming(
        self, conversation_id: ConversationId, phone: PhoneNumber, name: str, text: str
    ) -> None:
        try:
            chatwoot_conversation_id = await self._resolve_conversation(
                conversation_id, phone, name
            )
            await self._chatwoot_gateway.post_incoming_message(chatwoot_conversation_id, text)
        except Exception:  # noqa: BLE001 - mirror is best-effort, must never raise
            logger.warning(
                "mirror_to_chatwoot.mirror_incoming_failed conversation_id=%s",
                conversation_id,
                exc_info=True,
            )

    async def mirror_outgoing(
        self, conversation_id: ConversationId, phone: PhoneNumber, name: str, text: str
    ) -> None:
        try:
            chatwoot_conversation_id = await self._resolve_conversation(
                conversation_id, phone, name
            )
            await self._chatwoot_gateway.post_outgoing_message(chatwoot_conversation_id, text)
        except Exception:  # noqa: BLE001 - mirror is best-effort, must never raise
            logger.warning(
                "mirror_to_chatwoot.mirror_outgoing_failed conversation_id=%s",
                conversation_id,
                exc_info=True,
            )

    async def _resolve_conversation(
        self, conversation_id: ConversationId, phone: PhoneNumber, name: str
    ) -> str:
        async with self._mapping_repositories_provider() as mapping_repository:
            existing = await mapping_repository.get_by_conversation_id(str(conversation_id))
            if existing is not None:
                return existing.chatwoot_conversation_id

            contact_id, source_id = await self._chatwoot_gateway.find_or_create_contact(
                phone, name
            )
            chatwoot_conversation_id = await self._chatwoot_gateway.create_conversation(
                source_id, contact_id
            )
            await mapping_repository.save(
                ChatwootConversationMapping(
                    conversation_id=str(conversation_id),
                    chatwoot_contact_id=contact_id,
                    chatwoot_conversation_id=chatwoot_conversation_id,
                )
            )
            return chatwoot_conversation_id
