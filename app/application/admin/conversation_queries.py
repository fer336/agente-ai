from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.application.conversations.schedule_conversation_reset import (
    CONVERSATION_IDLE_RESET_ACTION,
)
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.conversation import Conversation
from app.domain.entities.error_record import ErrorRecord
from app.domain.entities.message import Message
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.error_repository import ErrorRepository
from app.domain.repositories.message_repository import MessageRepository
from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.domain.rules.conversation_timeouts import HUMAN_MODE_REACTIVATION_TIMEOUT
from app.domain.value_objects.conversation_id import ConversationId

#: What the countdown next to the control label is counting towards: the idle cleanup of
#: the agent's working memory (`mode="agent"`), or the lazy hand-back of a chat staff took
#: over (`mode="human"`).
ResetKind = Literal["idle_cleanup", "human_timeout"]


@dataclass
class ResetDeadline:
    at: datetime
    kind: ResetKind


@dataclass
class ConversationSummary:
    """One row of the `/admin/conversations` listing (PRD.md §44.1).

    `patient_or_identifier` is deliberately the conversation's internal
    `contact_id`, never a live Dentalink patient-name lookup — §44.1's own
    wording ("Paciente O identificador interno") allows this, and `Patient`
    is not a locally-persisted entity in this codebase (it only exists as a
    Dentalink-gateway shell), so resolving a display name here would mean
    one external API call per row on every panel page load.
    """

    conversation_id: str
    patient_or_identifier: str
    mode: str
    last_message_text: str | None
    last_message_at: datetime | None
    latest_run_status: str | None
    error_count: int
    reset_deadline: ResetDeadline | None


@dataclass
class ConversationDetail:
    """Backing data for `/admin/conversations/{id}` (PRD.md §44.2)."""

    conversation: Conversation
    messages: list[Message]
    agent_runs: list[AgentRun]
    errors: list[ErrorRecord]
    reset_deadline: ResetDeadline | None


class ConversationQueryService:
    """Read-only queries backing the admin panel's conversation views.

    Each summary row issues its own last-message/latest-run/error-count
    queries (no join) — acceptable at this MVP's scale (PRD.md §44: "no
    será un CRM ni un sistema comercial completo"); a future version
    wanting to page through thousands of conversations would want a single
    joined/aggregated query instead.
    """

    def __init__(
        self,
        conversations: ConversationRepository,
        messages: MessageRepository,
        agent_runs: AgentRunRepository,
        errors: ErrorRepository,
        scheduled_actions: ScheduledActionRepository,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._agent_runs = agent_runs
        self._errors = errors
        self._scheduled_actions = scheduled_actions

    async def list_conversations(self, limit: int = 50) -> list[ConversationSummary]:
        conversations = await self._conversations.list_recent(limit=limit)
        summaries = []
        for conversation in conversations:
            conversation_messages = await self._messages.get_by_conversation_id(conversation.id)
            last_message = conversation_messages[-1] if conversation_messages else None
            latest_run = await self._agent_runs.get_latest_by_conversation_id(conversation.id)
            conversation_errors = await self._errors.get_by_conversation_id(conversation.id)
            summaries.append(
                ConversationSummary(
                    conversation_id=str(conversation.id),
                    patient_or_identifier=conversation.contact_id,
                    mode=conversation.mode,
                    last_message_text=last_message.text if last_message else None,
                    last_message_at=last_message.created_at if last_message else None,
                    latest_run_status=latest_run.status if latest_run else None,
                    error_count=len(conversation_errors),
                    reset_deadline=await self._reset_deadline(conversation),
                )
            )
        return summaries

    async def get_conversation_detail(
        self, conversation_id: ConversationId
    ) -> ConversationDetail | None:
        conversation = await self._conversations.get_by_id(conversation_id)
        if conversation is None:
            return None

        return ConversationDetail(
            conversation=conversation,
            messages=await self._messages.get_by_conversation_id(conversation_id),
            agent_runs=await self._agent_runs.get_by_conversation_id(conversation_id),
            errors=await self._errors.get_by_conversation_id(conversation_id),
            reset_deadline=await self._reset_deadline(conversation),
        )

    async def _reset_deadline(self, conversation: Conversation) -> ResetDeadline | None:
        """When the countdown shown next to the control label reaches zero.

        Agent mode: the scheduled idle cleanup (`scheduled_for` already moves when the
        cleanup is deferred, so the countdown follows it). Human mode: the last staff
        reply plus the lazy timeout; `None` while staff never replied, because that
        handoff never expires.
        """
        if conversation.mode == "human":
            if conversation.last_human_reply_at is None:
                return None
            return ResetDeadline(
                at=conversation.last_human_reply_at + HUMAN_MODE_REACTIVATION_TIMEOUT,
                kind="human_timeout",
            )
        scheduled = await self._scheduled_actions.get_scheduled_by_conversation_id(
            str(conversation.id)
        )
        idle_resets = [a for a in scheduled if a.action_type == CONVERSATION_IDLE_RESET_ACTION]
        if not idle_resets:
            return None
        return ResetDeadline(at=min(a.scheduled_for for a in idle_resets), kind="idle_cleanup")
