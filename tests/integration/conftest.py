import socket
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.infrastructure.database.models import Base
from app.infrastructure.database.models.agent_run import AgentRunModel
from app.infrastructure.database.models.contact import ContactModel
from app.infrastructure.database.models.conversation import ConversationModel
from app.infrastructure.database.models.message import MessageModel
from app.infrastructure.database.models.pending_action import PendingActionModel
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
    await db_session.commit()
    return contact.id


@pytest.fixture
async def conversation_id(db_session: AsyncSession, contact_id: str) -> str:
    conversation = ConversationModel(id="conv-fixture", contact_id=contact_id, mode="agent")
    db_session.add(conversation)
    await db_session.commit()
    return conversation.id


@pytest.fixture
async def pending_action_id(db_session: AsyncSession, conversation_id: str) -> str:
    pending_action = PendingActionModel(
        id="pa-fixture",
        conversation_id=conversation_id,
        action_type="create_appointment",
        payload={},
        confirmation_token="token-fixture",
        status="pending",
        expires_at=datetime(2026, 8, 4, 9, 10, tzinfo=UTC),
    )
    db_session.add(pending_action)
    await db_session.flush()
    return pending_action.id


@pytest.fixture
async def message_id(db_session: AsyncSession, conversation_id: str) -> str:
    message = MessageModel(
        id="msg-fixture",
        conversation_id=conversation_id,
        external_message_id="wamid.fixture",
        direction="inbound",
        text="hola",
    )
    db_session.add(message)
    await db_session.flush()
    return message.id


@pytest.fixture
async def agent_run_id(db_session: AsyncSession, conversation_id: str, message_id: str) -> str:
    agent_run = AgentRunModel(
        id="run-fixture",
        conversation_id=conversation_id,
        message_id=message_id,
        trace_id="trace-fixture",
        prompt_version="agent-system-v0.1.0",
        model="gpt-4o-mini",
        started_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        status="running",
    )
    db_session.add(agent_run)
    await db_session.flush()
    return agent_run.id
