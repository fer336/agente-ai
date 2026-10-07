from typing import Any

from app.api.dependencies.gateways import get_llm_provider
from app.api.dependencies.redis import get_shared_redis_client
from app.api.dependencies.repositories import open_sqlalchemy_workflow_session_repositories
from app.application.conversations.cleanup_conversation_session import (
    CleanupConversationSessionUseCase,
)
from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.conversations.schedule_conversation_reset import (
    ScheduleConversationResetUseCase,
)
from app.application.memory.memory_service import MemoryService
from app.config.settings import get_settings
from app.infrastructure.agent.langgraph_session_checkpoint_repository import (
    LangGraphSessionCheckpointRepository,
)
from app.workers.follow_up_worker import FollowUpWorkerRepositories


def build_idle_cleanup_use_case(
    repositories: FollowUpWorkerRepositories, checkpointer: Any
) -> CleanupConversationSessionUseCase | None:
    """`run_follow_up_loop`'s `cleanup_factory` for production DI: wires the
    scoped idle cleanup onto one tick's repositories. Returns `None` (the
    worker then keeps its plain rotation) when a dependency is missing.
    """
    if repositories.contact_memories is None or checkpointer is None:
        return None
    return CleanupConversationSessionUseCase(
        conversations=repositories.conversations,
        contacts=repositories.contacts,
        rotate_workflow_session=RotateWorkflowSessionUseCase(
            open_sqlalchemy_workflow_session_repositories
        ),
        session_checkpoints=LangGraphSessionCheckpointRepository(checkpointer),
        memory_service=MemoryService(
            contact_memory_repository=repositories.contact_memories,
            message_repository=repositories.messages,
            llm_provider=get_llm_provider(),
            recent_window_size=get_settings().memory_recent_window_size,
            redis_client=get_shared_redis_client(),
        ),
        appointment_reminders=repositories.appointment_reminders,
        schedule_conversation_reset=ScheduleConversationResetUseCase(
            repositories.scheduled_actions, get_settings().conversation_idle_reset_delay_seconds
        ),
    )
