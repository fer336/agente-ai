from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import _get_session_factory, get_db_session
from app.application.messages.ingest_message import MessageRepositories
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.message_repository import MessageRepository
from app.infrastructure.database.repositories.contact_repository import SqlAlchemyContactRepository
from app.infrastructure.database.repositories.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from app.infrastructure.database.repositories.message_repository import SqlAlchemyMessageRepository


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
