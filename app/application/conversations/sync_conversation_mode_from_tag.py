from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    HUMAN,
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import MessagingGateway
from app.domain.value_objects.conversation_id import ConversationId

_INPUT_STATE_FOR_MODE = {"human": HUMAN, "agent": FREE_INPUT}


class SyncConversationModeFromTagUseCase:
    """Flips `conversation.mode` when a human agent adds or removes the
    "Human" tag on a YCloud contact from the Shared Team Inbox.

    Counterpart to `app.agent.nodes.handoff`'s one-way flip to `"human"` —
    that node has no way back to `"agent"` once a human takes over; this is
    the return path, driven from YCloud rather than a not-yet-built admin
    UI. Also resets `input_state` alongside `mode`, mirroring
    `handoff.py`'s own paired write, so a resumed conversation isn't left
    stuck in `HUMAN` input state.

    Silently no-ops (does not raise) when the contact's phone can't be
    resolved or no matching conversation exists yet — a tag applied to a
    contact who never messaged us, or a since-deleted conversation, is not
    an error worth surfacing to YCloud's webhook retry logic.
    """

    def __init__(
        self,
        messaging_gateway: MessagingGateway,
        conversation_repository: ConversationRepository,
    ) -> None:
        self._messaging_gateway = messaging_gateway
        self._conversation_repository = conversation_repository
        self._set_conversation_mode = SetConversationModeUseCase(conversation_repository)
        self._set_conversation_input_state = SetConversationInputStateUseCase(
            conversation_repository
        )

    async def execute(self, ycloud_contact_id: str, mode: str) -> None:
        phone = await self._messaging_gateway.get_contact_phone(ycloud_contact_id)
        if phone is None:
            return

        conversation_id = ConversationId(f"ycloud-{phone}")
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return

        await self._set_conversation_mode.execute(conversation_id, mode)
        input_state = _INPUT_STATE_FOR_MODE.get(mode)
        if input_state is not None:
            await self._set_conversation_input_state.execute(conversation_id, input_state)
