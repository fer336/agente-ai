import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.pending_action_repository import PendingActionRepository
from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.domain.value_objects.conversation_id import ConversationId

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowSessionRepositories:
    """Ports needed to rotate operational state in one durable transaction."""

    conversations: ConversationRepository
    pending_actions: PendingActionRepository
    scheduled_actions: ScheduledActionRepository


WorkflowSessionRepositoriesProvider = Callable[
    [], AbstractAsyncContextManager[WorkflowSessionRepositories]
]


class RotateWorkflowSessionUseCase:
    """Advances workflow state and retires still-pending old-generation actions.

    The conversation CAS is the admission gate: only its winner may expire
    actions. Each action transition keeps its own status guard, so a concurrent
    confirmation can win exactly once without a stale rotation overwriting it.
    """

    Repositories = WorkflowSessionRepositories

    def __init__(
        self,
        conversations: ConversationRepository | WorkflowSessionRepositoriesProvider,
    ) -> None:
        self._conversations = conversations if not callable(conversations) else None
        self._repositories_provider = conversations if callable(conversations) else None

    @staticmethod
    def is_inactive(previous_activity_at: datetime | None, received_at: datetime) -> bool:
        return previous_activity_at is not None and received_at - previous_activity_at > timedelta(
            hours=1
        )

    async def execute(
        self,
        conversation_id: ConversationId,
        *,
        expected_generation: int,
        expire_all_pending_generations: bool = False,
    ) -> bool:
        """`expire_all_pending_generations`: T4 (R3-new-conversation-
        rotation-can-collide-with-prior-incarnation-generation) — a
        genuinely brand-new conversation row's seeded generation (see
        `ingest_message.py`'s seeding helper) is already unique-enough on
        its own, but any pending action still on record for that
        conversation id from BEFORE the row existed is stale no matter
        which generation number it recorded, not only the one exact
        `expected_generation` this call happens to pass. The default
        (`False`) keeps the narrower, exactly-this-generation behavior the
        inactivity-rotation call site still relies on, where the
        conversation continuously existed and only one generation is being
        retired at a time.
        """
        if self._repositories_provider is None:
            assert self._conversations is not None
            if expire_all_pending_generations:
                # T5 (review-2358088d31f27658, R3-expire-all-flag-ignored-
                # without-repositories-provider): this constructor shape has
                # no `pending_actions`/`scheduled_actions` repositories at
                # all — the flag can never be honored here, not even the
                # narrower per-generation expiry the `repositories_provider`
                # branch below always does. Silently ignoring an explicit
                # request would hide a wiring bug instead of surfacing it;
                # rotation itself is still best-effort/self-healing (see
                # `ingest_message.py`'s own call site), so this warns rather
                # than raising.
                logger.warning(
                    "expire_all_pending_generations=True requested for "
                    "conversation %s but this RotateWorkflowSessionUseCase "
                    "was built with only a bare ConversationRepository (no "
                    "repositories_provider) — the flag has no effect and no "
                    "pending action is expired on this path at all.",
                    conversation_id,
                )
            return await self._conversations.rotate_workflow_session(
                conversation_id, expected_generation
            )

        async with self._repositories_provider() as repositories:
            rotated = await repositories.conversations.rotate_workflow_session(
                conversation_id, expected_generation
            )
            if not rotated:
                return False

            stale_actions = (
                await repositories.pending_actions.get_pending_for_conversation(conversation_id)
                if expire_all_pending_generations
                else await repositories.pending_actions.get_pending_for_conversation_generation(
                    conversation_id, expected_generation
                )
            )
            for pending_action in stale_actions:
                if not await repositories.pending_actions.mark_expired_if_pending(
                    pending_action.id
                ):
                    continue
                scheduled_action = await repositories.scheduled_actions.get_by_pending_action_id(
                    pending_action.id
                )
                if scheduled_action is not None:
                    await repositories.scheduled_actions.transition_status(
                        scheduled_action.id, from_status="scheduled", to_status="cancelled"
                    )
            return True
