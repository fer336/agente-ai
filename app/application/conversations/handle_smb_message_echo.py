import logging
from datetime import UTC, datetime, timedelta

from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    HUMAN,
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.domain.entities.conversation import Conversation
from app.domain.repositories.conversation_ad_referral_repository import (
    ConversationAdReferralRepository,
)
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId

logger = logging.getLogger(__name__)

#: How long after a lead's Click-to-WhatsApp ad message a business-sent echo is
#: read as Meta's automatic ad welcome instead of a staff takeover.
#:
#: ASSUMPTION (unverified, no live payload yet): Meta sends the ad's welcome
#: message from the business number right after the lead's first message, and on
#: a Coexistence number YCloud may deliver it as `whatsapp.smb.message.echoes`.
#: Treated as a staff reply it would flip every ad lead to human mode and silence
#: the bot. The guard is deliberately narrow: only inside this window, only for a
#: conversation that has an ad referral, and never for `/bot` or `/adm`. The cost
#: of a false positive is that a staff reply typed within a minute of the lead's
#: first ad message does not pause the bot.
AD_WELCOME_ECHO_WINDOW = timedelta(seconds=60)


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

    A staff message (anything but `/bot`) to a conversation still in
    `mode="agent"` pauses the bot: `mode` flips to `"human"`, `input_state` to
    `HUMAN`, and `last_human_reply_at` is stamped, so the lazy timeout or `/bot`
    hands it back, and nothing else happens on that call.

    Otherwise (the conversation is already human, or the message is `/bot`),
    two independent effects can fire, not mutually exclusive branches
    (confirmed with the user: "se reinicia cada vez que el humano manda un
    mensaje"):

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

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        ad_referral_repository: ConversationAdReferralRepository | None = None,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._ad_referral_repository = ad_referral_repository
        self._set_conversation_mode = SetConversationModeUseCase(conversation_repository)
        self._set_conversation_input_state = SetConversationInputStateUseCase(
            conversation_repository
        )

    async def execute(
        self,
        patient_phone: str,
        *,
        is_reactivation_command: bool,
        is_staff_command: bool = False,
    ) -> bool:
        """Applies the echo. Returns `True` when it was ignored as Meta's ad
        welcome message (see `AD_WELCOME_ECHO_WINDOW`), `False` otherwise.

        `is_staff_command` is true for `/bot` and `/adm`: a deliberate command
        is never mistaken for the ad welcome.
        """
        conversation_id = ConversationId(f"ycloud-{patient_phone}")
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return False

        if conversation.mode == "agent" and not is_reactivation_command:
            if not is_staff_command and await self._is_ad_welcome_echo(conversation_id):
                logger.info("smb_echo.ignored_as_ad_welcome conversation=%s", conversation_id)
                return True
            # Staff wrote from the WhatsApp Business app or WhatsApp Web: they took the
            # chat over, so the bot stops answering (same state as a handoff). `/bot` or
            # the lazy timeout hands it back.
            await self._set_conversation_mode.execute(conversation_id, "human")
            await self._set_conversation_input_state.execute(conversation_id, HUMAN)
            paused = await self._conversation_repository.get_by_id(conversation_id)
            if paused is not None:
                await self._touch_last_human_reply(paused)
            return False

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
        return False

    async def _is_ad_welcome_echo(self, conversation_id: ConversationId) -> bool:
        if self._ad_referral_repository is None:
            return False
        try:
            referral = await self._ad_referral_repository.get_latest_for_conversation(
                conversation_id
            )
        except Exception:
            # Fail open to the established behavior: a lookup problem must not
            # change how staff replies are handled.
            logger.warning(
                "smb_echo.ad_referral_lookup_failed conversation=%s",
                conversation_id,
                exc_info=True,
            )
            return False
        if referral is None:
            return False
        return datetime.now(UTC) - referral.first_seen_at <= AD_WELCOME_ECHO_WINDOW

    async def _stamp_fresh_restart(self, conversation_id: ConversationId) -> None:
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return
        conversation.awaiting_fresh_restart = True
        await self._conversation_repository.save(conversation)

    async def _touch_last_human_reply(self, conversation: Conversation) -> None:
        # Mutate in place — reconstructing a `Conversation` with a
        # hand-picked field list (the previous approach here) silently
        # drops `workflow_session_generation`/`workflow_last_activity_at`/
        # `awaiting_fresh_restart` back to their dataclass defaults; see
        # `SetConversationInputStateUseCase`'s own comment for the full
        # story — same bug, same fix, different call site.
        conversation.last_human_reply_at = datetime.now(UTC)
        await self._conversation_repository.save(conversation)
