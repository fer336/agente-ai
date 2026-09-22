import logging

from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.domain.repositories.chatwoot_gateway import ChatwootGateway
from app.domain.repositories.chatwoot_mapping_repository import ChatwootMappingRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId

logger = logging.getLogger(__name__)


class ReactivateBotFromChatwootUseCase:
    """Flips `conversation.mode` back to `"agent"` when staff resolves the
    conversation in Chatwoot — confirmed with the user as the SOLE
    authoritative return-to-bot path ("SOLO DESDE CHATWOOOT"), replacing
    reliance on YCloud's own contact-tag mechanism for this (documented as
    unreliable for Coexistence-connected contacts — see
    `app.application.conversations.handle_smb_message_echo`'s own
    docstring). Does NOT replace the existing `/bot` command or YCloud tag
    paths — both keep working in parallel, per this session's own plan.

    No-ops (does not raise) when no mapping exists for this Chatwoot
    conversation — a `resolved` event for a conversation we never mirrored
    (e.g. created directly in Chatwoot) has nothing to reactivate.
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

    async def execute(self, chatwoot_conversation_id: str) -> None:
        mapping = await self._mapping_repository.get_by_chatwoot_conversation_id(
            chatwoot_conversation_id
        )
        if mapping is None:
            return

        conversation_id = ConversationId(mapping.conversation_id)
        await self._set_conversation_mode.execute(conversation_id, mode="agent")
        await self._set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        # Reflects the flip back in Chatwoot's own label too, so the
        # dashboard never disagrees with what conversation.mode says —
        # best-effort: this use case's own no-raise contract on a missing
        # mapping already sets the "never break the ack" precedent, but a
        # label-set failure specifically must not undo the mode flip that
        # already succeeded above.
        try:
            await self._chatwoot_gateway.assign_bot(chatwoot_conversation_id)
        except Exception:  # noqa: BLE001 - label sync is best-effort
            logger.warning(
                "reactivate_bot_from_chatwoot.label_sync_failed "
                "chatwoot_conversation_id=%s",
                chatwoot_conversation_id,
                exc_info=True,
            )
