import socket
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.infrastructure.database.models import Base
from app.infrastructure.database.models.contact import ContactModel
from app.infrastructure.database.models.conversation import ConversationModel
from app.infrastructure.database.session import create_engine, create_session_factory


def _postgres_reachable() -> bool:
    settings = get_settings()
    try:
        with socket.create_connection((settings.postgres_host, settings.postgres_port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable for repository integration test")

    settings = get_settings()
    engine = create_engine(settings.database_url)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        yield session

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def contact_id(db_session: AsyncSession) -> str:
    contact = ContactModel(id="contact-fixture", phone="+5491100000000")
    db_session.add(contact)
    await db_session.flush()
    return contact.id


@pytest.fixture
async def conversation_id(db_session: AsyncSession, contact_id: str) -> str:
    conversation = ConversationModel(id="conv-fixture", contact_id=contact_id, mode="agent")
    db_session.add(conversation)
    await db_session.flush()
    return conversation.id
