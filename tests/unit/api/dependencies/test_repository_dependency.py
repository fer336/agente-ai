from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import get_db_session
from app.api.dependencies.repositories import (
    get_contact_repository,
    get_conversation_repository,
    get_incident_repository,
    get_message_repository,
    open_sqlalchemy_appointment_reminder_worker_repositories,
)
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.incident_repository import IncidentRepository
from app.domain.repositories.message_repository import MessageRepository
from app.infrastructure.database.repositories.appointment_reminder_repository import (
    SqlAlchemyAppointmentReminderRepository,
)
from app.infrastructure.database.repositories.contact_repository import SqlAlchemyContactRepository
from app.infrastructure.database.repositories.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from app.infrastructure.database.repositories.incident_repository import (
    SqlAlchemyIncidentRepository,
)
from app.infrastructure.database.repositories.message_repository import SqlAlchemyMessageRepository


@pytest.mark.asyncio
async def test_get_contact_repository_returns_a_sqlalchemy_contact_repository():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        repository = get_contact_repository(session)

        assert isinstance(repository, SqlAlchemyContactRepository)
        assert isinstance(repository, ContactRepository)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_message_repository_returns_a_sqlalchemy_message_repository():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        repository = get_message_repository(session)

        assert isinstance(repository, SqlAlchemyMessageRepository)
        assert isinstance(repository, MessageRepository)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_conversation_repository_returns_a_sqlalchemy_conversation_repository():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        repository = get_conversation_repository(session)

        assert isinstance(repository, SqlAlchemyConversationRepository)
        assert isinstance(repository, ConversationRepository)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_incident_repository_returns_a_sqlalchemy_incident_repository():
    generator = get_db_session()
    session: AsyncSession = await generator.__anext__()
    try:
        repository = get_incident_repository(session)

        assert isinstance(repository, SqlAlchemyIncidentRepository)
        assert isinstance(repository, IncidentRepository)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_reminder_worker_repository_provider_uses_fresh_session_and_commits(monkeypatch):
    session = AsyncMock()

    @asynccontextmanager
    async def session_context():
        yield session

    monkeypatch.setattr(
        "app.api.dependencies.repositories._get_session_factory", lambda: session_context
    )

    async with open_sqlalchemy_appointment_reminder_worker_repositories() as repositories:
        assert isinstance(repositories.reminders, SqlAlchemyAppointmentReminderRepository)
        assert isinstance(repositories.contacts, SqlAlchemyContactRepository)

    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reminder_worker_repository_provider_rolls_back_on_failure(monkeypatch):
    session = AsyncMock()

    @asynccontextmanager
    async def session_context():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    monkeypatch.setattr(
        "app.api.dependencies.repositories._get_session_factory", lambda: session_context
    )

    with pytest.raises(RuntimeError, match="boom"):
        async with open_sqlalchemy_appointment_reminder_worker_repositories():
            raise RuntimeError("boom")

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
