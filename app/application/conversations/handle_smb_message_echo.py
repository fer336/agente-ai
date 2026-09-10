from datetime import UTC, datetime

from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.domain.entities.conversation import Conversation
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId


class HandleSmbMessageEchoUseCase:
    """Handles a YCloud `whatsapp.smb.message.echoes` event: an outbound
    WhatsApp message a human staff member typed directly in the WhatsApp
    Business App (or a linked companion device), addressed to a patient.

    Replaces the YCloud contact-tag mechanism
    (`SyncConversationModeFromTagUseCase`) as the primary way to hand a
    conversation back from `mode="human"` to `mode="agent"` — confirmed
    live against this project's real YCloud account that tag PATCH calls
    return 200 OK but do not persist on Coexistence-connected contacts
    (`sourceType="SMB"`), making the tag toggle unreliable for this
    project's actual production setup.

    Two independent effects fire on every call, not mutually exclusive
    branches (confirmed with the user: "se reinicia cada vez que el
    humano manda un mensaje"):

    1. If the conversation is currently `mode="human"`, `last_human_reply_at`
       is stamped with `now()` — resetting the lazy-timeout clock
       `IngestMessageUseCase` reads (see its module-level constant).
       Skipped when the conversation is already `mode="agent"` (nothing to
       reset) or doesn't exist yet.
    2. If the echoed message's text is exactly `/bot` (case-insensitive,
       trimmed — see `webhook_parser.extract_bot_reactivation_command`),
       `mode` flips back to `"agent"` immediately and `input_state` resets
       to `FREE_INPUT`, mirroring `SyncConversationModeFromTagUseCase`'s
       own paired write for the same transition. It ALSO atomically rotates
       the workflow session (CAS on the generation — the old stage /
       collected_data die with the previous generation) and, when the
       rotation wins, stamps `awaiting_fresh_restart` so the NEXT agent
       turn renders the canonical welcome menu deterministically instead
       of LLM-continuing the old thread. Durable messages/ContactMemory
       are never touched.
       A rotation CAS failure (a concurrent turn already rotated) must NOT
       stamp the flag — that turn already consumed the fresh start.

    Silently no-ops when no conversation exists yet for the patient phone
    — ack-and-drop, same convention as `SyncConversationModeFromTagUseCase`
    (a staff member replying to a phone number that never messaged us, or
    a since-deleted conversation, is not an error worth surfacing to
    YCloud's webhook retry logic).
    """

    def __init__(self, conversation_repository: ConversationRepository) -> None:
        self._conversation_repository = conversation_repository
        self._set_conversation_mode = SetConversationModeUseCase(conversation_repository)
        self._set_conversation_input_state = SetConversationInputStateUseCase(
            conversation_repository
        )

    async def execute(self, patient_phone: str, *, is_reactivation_command: bool) -> None:
        conversation_id = ConversationId(f"ycloud-{patient_phone}")
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return

        if conversation.mode == "human":
            await self._touch_last_human_reply(conversation)

        if is_reactivation_command:
            await self._set_conversation_mode.execute(conversation_id, "agent")
            await self._set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            rotation_won = await self._conversation_repository.rotate_workflow_session(
                conversation_id, conversation.workflow_session_generation
            )
            if rotation_won:
                await self._stamp_fresh_restart(conversation_id)

    async def _stamp_fresh_restart(self, conversation_id: ConversationId) -> None:
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return
        conversation.awaiting_fresh_restart = True
        await self._conversation_repository.save(conversation)

    async def _touch_last_human_reply(self, conversation: Conversation) -> None:
        updated = Conversation(
            id=conversation.id,
            contact_id=conversation.contact_id,
            mode=conversation.mode,
            created_at=conversation.created_at,
            input_state=conversation.input_state,
            last_human_reply_at=datetime.now(UTC),
        )
        await self._conversation_repository.save(updated)
