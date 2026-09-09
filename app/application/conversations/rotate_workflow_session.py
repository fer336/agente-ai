from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.pending_action_repository import PendingActionRepository
from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.domain.value_objects.conversation_id import ConversationId


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

    async def execute(self, conversation_id: ConversationId, *, expected_generation: int) -> bool:
        if self._repositories_provider is None:
            assert self._conversations is not None
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
                await repositories.pending_actions.get_pending_for_conversation_generation(
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
