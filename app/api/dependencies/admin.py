from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import get_committing_db_session, get_db_session
from app.application.admin.authenticate_admin import AuthenticateAdminUseCase
from app.application.admin.conversation_queries import ConversationQueryService
from app.application.admin.error_queries import ErrorQueryService
from app.application.admin.run_queries import RunQueryService
from app.config.settings import Settings, get_settings
from app.infrastructure.database.repositories.admin_audit_log_repository import (
    SqlAlchemyAdminAuditLogRepository,
)
from app.infrastructure.database.repositories.admin_user_repository import (
    SqlAlchemyAdminUserRepository,
)
from app.infrastructure.database.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)
from app.infrastructure.database.repositories.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from app.infrastructure.database.repositories.error_repository import SqlAlchemyErrorRepository
from app.infrastructure.database.repositories.message_repository import SqlAlchemyMessageRepository
from app.infrastructure.database.repositories.node_execution_repository import (
    SqlAlchemyNodeExecutionRepository,
)
from app.infrastructure.database.repositories.tool_execution_repository import (
    SqlAlchemyToolExecutionRepository,
)


def get_authenticate_admin_use_case(
    session: AsyncSession = Depends(get_committing_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthenticateAdminUseCase:
    """Built fresh per request (not `@lru_cache`d) — unlike `IngestMessageUseCase`,
    this use case holds no cross-request state, so there is no reason to
    pin it (and its session) to whichever request happens to build it first.
    """
    return AuthenticateAdminUseCase(
        admin_user_repository=SqlAlchemyAdminUserRepository(session),
        admin_audit_log_repository=SqlAlchemyAdminAuditLogRepository(session),
        session_secret=settings.admin_session_secret,
        session_ttl_seconds=settings.admin_session_ttl_seconds,
    )


def get_conversation_query_service(
    session: AsyncSession = Depends(get_db_session),
) -> ConversationQueryService:
    return ConversationQueryService(
        conversations=SqlAlchemyConversationRepository(session),
        messages=SqlAlchemyMessageRepository(session),
        agent_runs=SqlAlchemyAgentRunRepository(session),
        errors=SqlAlchemyErrorRepository(session),
    )


def get_error_query_service(
    session: AsyncSession = Depends(get_db_session),
) -> ErrorQueryService:
    """Read-only wiring — routes that mutate (`resolve`) use
    `get_committing_error_query_service` instead so that write survives
    past the request.
    """
    return ErrorQueryService(SqlAlchemyErrorRepository(session))


def get_committing_error_query_service(
    session: AsyncSession = Depends(get_committing_db_session),
) -> ErrorQueryService:
    return ErrorQueryService(SqlAlchemyErrorRepository(session))


def get_run_query_service(session: AsyncSession = Depends(get_db_session)) -> RunQueryService:
    return RunQueryService(
        agent_runs=SqlAlchemyAgentRunRepository(session),
        node_executions=SqlAlchemyNodeExecutionRepository(session),
        tool_executions=SqlAlchemyToolExecutionRepository(session),
    )
