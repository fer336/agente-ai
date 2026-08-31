import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import get_db_session
from app.api.dependencies.repositories import (
    get_contact_repository,
    get_conversation_repository,
    get_incident_repository,
    get_message_repository,
)
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.incident_repository import IncidentRepository
from app.domain.repositories.message_repository import MessageRepository
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
