from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import _get_session_factory, get_db_session
from app.application.appointments.propose_appointment import ProposalRepositories
from app.application.messages.ingest_message import MessageRepositories
from app.application.observability.trace_repositories import TraceRepositories
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.message_repository import MessageRepository
from app.infrastructure.agent.langgraph_agent_invoker import AgentRepositories
from app.infrastructure.database.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)
from app.infrastructure.database.repositories.contact_repository import SqlAlchemyContactRepository
from app.infrastructure.database.repositories.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from app.infrastructure.database.repositories.error_repository import SqlAlchemyErrorRepository
from app.infrastructure.database.repositories.message_repository import SqlAlchemyMessageRepository
from app.infrastructure.database.repositories.node_execution_repository import (
    SqlAlchemyNodeExecutionRepository,
)
from app.infrastructure.database.repositories.outbox_repository import SqlAlchemyOutboxRepository
from app.infrastructure.database.repositories.pending_action_repository import (
    SqlAlchemyPendingActionRepository,
)
from app.infrastructure.database.repositories.scheduled_action_repository import (
    SqlAlchemyScheduledActionRepository,
)
from app.infrastructure.database.repositories.tool_execution_repository import (
    SqlAlchemyToolExecutionRepository,
)


def get_contact_repository(session: AsyncSession = Depends(get_db_session)) -> ContactRepository:
    """FastAPI dependency providing the `ContactRepository` port.

    Unlike the still-fake domain gateways in `app.api.dependencies.gateways`
    (`AppointmentGateway`, `MessagingGateway`, ... — waiting on later
    etapas' real integrations), Etapa 2 already built the real Postgres-
    backed `SqlAlchemyContactRepository`, so this returns it directly,
    bound to the request-scoped session.
    """
    return SqlAlchemyContactRepository(session)


def get_message_repository(session: AsyncSession = Depends(get_db_session)) -> MessageRepository:
    """FastAPI dependency providing the `MessageRepository` port (real, Postgres-backed)."""
    return SqlAlchemyMessageRepository(session)


def get_conversation_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ConversationRepository:
    """FastAPI dependency providing the `ConversationRepository` port (real, Postgres-backed)."""
    return SqlAlchemyConversationRepository(session)


@asynccontextmanager
async def open_sqlalchemy_message_repositories() -> AsyncIterator[MessageRepositories]:
    """`IngestMessageUseCase`'s `repositories_provider` for production DI.

    Opens a FRESH session — via the app-lifetime cached
    `app.api.dependencies.db._get_session_factory()`, not the per-request
    `Depends(get_db_session)` — every time it is called. `IngestMessageUseCase`
    is a process-level singleton (see `app.api.dependencies.use_cases`) whose
    deferred `_debounce_and_process` step runs well after any one HTTP
    request/response cycle ends, so it must never reuse a request-scoped
    session that has already been closed by then.
    """
    session_factory = _get_session_factory()
    async with session_factory() as session:
        yield MessageRepositories(
            messages=SqlAlchemyMessageRepository(session),
            contacts=SqlAlchemyContactRepository(session),
            conversations=SqlAlchemyConversationRepository(session),
        )


@asynccontextmanager
async def open_sqlalchemy_agent_repositories() -> AsyncIterator[AgentRepositories]:
    """`LangGraphAgentInvoker`'s `repositories_provider` for production DI.

    Same rationale as `open_sqlalchemy_message_repositories` above: opens a
    FRESH session per call rather than reusing a request-scoped one, since
    `LangGraphAgentInvoker` is a process-level singleton too.
    """
    session_factory = _get_session_factory()
    async with session_factory() as session:
        yield AgentRepositories(
            conversations=SqlAlchemyConversationRepository(session),
            contacts=SqlAlchemyContactRepository(session),
        )


@asynccontextmanager
async def open_sqlalchemy_proposal_repositories() -> AsyncIterator[ProposalRepositories]:
    """`ProposeAppointmentUseCase`'s `repositories_provider` for production DI.

    Unlike `open_sqlalchemy_message_repositories`/`open_sqlalchemy_agent_repositories`
    above (which never call `.commit()` — see their own module's callers'
    docstrings for the pre-existing "same session, read-your-writes-only"
    behavior this codebase has relied on so far), this ONE provider commits
    explicitly before the `async with` block exits. PRD.md §16.2 requires
    the `PendingAction` + `ScheduledAction` + initial outbox event to exist
    together, durably, in a single transaction — a session that's merely
    `close()`d without `commit()` never persists anything past that same
    session, which would silently violate that guarantee the moment a
    second, later request needs to see this proposal (e.g. the confirm/
    reject turn, or the not-yet-built expiry worker). Scoped to only this
    transaction, not a blanket fix — see this change's report.
    """
    session_factory = _get_session_factory()
    async with session_factory() as session:
        yield ProposalRepositories(
            pending_actions=SqlAlchemyPendingActionRepository(session),
            scheduled_actions=SqlAlchemyScheduledActionRepository(session),
            outbox=SqlAlchemyOutboxRepository(session),
        )
        await session.commit()


@asynccontextmanager
async def open_sqlalchemy_trace_repositories() -> AsyncIterator[TraceRepositories]:
    """`TraceRepositoriesProvider` for production DI (PRD.md §38-42).

    Commits explicitly, same reasoning as `open_sqlalchemy_proposal_repositories`
    above: this data exists specifically to be queried later (incident
    review, a future admin panel), so a session that's merely `close()`d
    without `commit()` would silently discard it. One session per
    `LangGraphAgentInvoker.handle()` call — every `NodeExecution` written
    during that turn's graph run, plus both the initial and final `AgentRun`
    write, share it and commit together at the end.
    """
    session_factory = _get_session_factory()
    async with session_factory() as session:
        yield TraceRepositories(
            agent_runs=SqlAlchemyAgentRunRepository(session),
            node_executions=SqlAlchemyNodeExecutionRepository(session),
            tool_executions=SqlAlchemyToolExecutionRepository(session),
            errors=SqlAlchemyErrorRepository(session),
        )
        await session.commit()
