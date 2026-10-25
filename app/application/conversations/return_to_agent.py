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


class ReturnConversationToAgentUseCase:
    """Hands a human-mode conversation back to the agent from the admin panel.

    Same effect as the `/bot` staff command (`HandleSmbMessageEchoUseCase`): the mode
    flips to `"agent"`, the input state is cleared and the workflow session is
    rotated, so the next patient message starts from the welcome menu instead of
    continuing a stale thread. A conversation already under the agent is left
    untouched (rotating it would throw away a live workflow).

    The Chatwoot "agente" label is best-effort and only applied when a mapping already
    exists: the durable state is the local row, and the panel must not create Chatwoot
    conversations.
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        mapping_repository: ChatwootMappingRepository,
        chatwoot_gateway: ChatwootGateway,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._mapping_repository = mapping_repository
        self._chatwoot_gateway = chatwoot_gateway
        self._set_conversation_mode = SetConversationModeUseCase(conversation_repository)
        self._set_conversation_input_state = SetConversationInputStateUseCase(
            conversation_repository
        )

    async def execute(self, conversation_id: ConversationId) -> bool:
        """`False` when the conversation does not exist, `True` otherwise."""
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return False
        if conversation.mode == "agent":
            return True

        await self._set_conversation_mode.execute(conversation_id, "agent")
        await self._set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        rotated = await self._conversation_repository.rotate_workflow_session(
            conversation_id, conversation.workflow_session_generation
        )
        if rotated:
            await self._stamp_fresh_restart(conversation_id)
        await self._sync_label(conversation_id)
        return True

    async def _stamp_fresh_restart(self, conversation_id: ConversationId) -> None:
        # Re-read: the mode and input-state writes saved fresh objects, so a copy taken
        # before them would revert those fields.
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return
        conversation.awaiting_fresh_restart = True
        await self._conversation_repository.save(conversation)

    async def _sync_label(self, conversation_id: ConversationId) -> None:
        try:
            mapping = await self._mapping_repository.get_by_conversation_id(str(conversation_id))
            if mapping is None:
                return
            await self._chatwoot_gateway.assign_bot(mapping.chatwoot_conversation_id)
        except Exception:  # noqa: BLE001 - the mode flip is already durable
            logger.warning(
                "return_to_agent.label_sync_failed conversation_id=%s",
                conversation_id,
                exc_info=True,
            )
