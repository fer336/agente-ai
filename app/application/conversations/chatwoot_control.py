import logging

from app.application.conversations.set_conversation_input_state import (
    HUMAN,
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.domain.repositories.chatwoot_gateway import ChatwootGateway
from app.domain.repositories.chatwoot_mapping_repository import ChatwootMappingRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId

logger = logging.getLogger(__name__)


class PauseBotFromChatwootUseCase:
    """Pauses the agent when Chatwoot staff explicitly takes control.

    The durable source of truth remains the local conversation row. Label
    synchronization is optional and best-effort: a staff message must still
    pause the bot even if Chatwoot refuses the cosmetic label update.
    """

    def __init__(
        self,
        chatwoot_gateway: ChatwootGateway,
        conversation_repository: ConversationRepository,
        mapping_repository: ChatwootMappingRepository,
    ) -> None:
        self._chatwoot_gateway = chatwoot_gateway
        self._mapping_repository = mapping_repository
        self._set_conversation_mode = SetConversationModeUseCase(conversation_repository)
        self._set_conversation_input_state = SetConversationInputStateUseCase(
            conversation_repository
        )

    async def execute(
        self, chatwoot_conversation_id: str, *, synchronize_label: bool = False
    ) -> None:
        mapping = await self._mapping_repository.get_by_chatwoot_conversation_id(
            chatwoot_conversation_id
        )
        if mapping is None:
            return

        conversation_id = ConversationId(mapping.conversation_id)
        await self._set_conversation_mode.execute(conversation_id, mode="human")
        await self._set_conversation_input_state.execute(conversation_id, HUMAN)

        if not synchronize_label:
            return
        try:
            await self._chatwoot_gateway.assign_administracion(chatwoot_conversation_id)
        except Exception:  # noqa: BLE001 - control state is already durable
            logger.warning(
                "pause_bot_from_chatwoot.label_sync_failed "
                "chatwoot_conversation_id=%s",
                chatwoot_conversation_id,
                exc_info=True,
            )
