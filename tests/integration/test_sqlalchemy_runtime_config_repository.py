from datetime import UTC, datetime

from app.domain.entities.runtime_agent_config import RuntimeAgentConfig
from app.infrastructure.database.repositories.runtime_config_repository import (
    SqlAlchemyRuntimeConfigRepository,
)


def _config(model: str = "gemini/gemini-3.7-flash") -> RuntimeAgentConfig:
    now = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
    return RuntimeAgentConfig(
        id="default",
        model=model,
        temperature=0.0,
        debounce_seconds=6,
        classify_intent_prompt="classify this",
        extract_information_prompt="extract {required_fields}",
        generate_response_prompt="respond to {intent} with {collected_data}",
        updated_at=now,
        updated_by="admin-1",
    )


async def test_get_returns_none_when_missing(db_session):
    repository = SqlAlchemyRuntimeConfigRepository(db_session)

    assert await repository.get() is None


async def test_save_then_get_round_trips(db_session):
    repository = SqlAlchemyRuntimeConfigRepository(db_session)

    await repository.save(_config())
    fetched = await repository.get()

    assert fetched is not None
    assert fetched.model == "gemini/gemini-3.7-flash"
    assert fetched.debounce_seconds == 6


async def test_save_overwrites_the_single_row(db_session):
    repository = SqlAlchemyRuntimeConfigRepository(db_session)
    await repository.save(_config(model="first-model"))

    await repository.save(_config(model="second-model"))

    fetched = await repository.get()
    assert fetched is not None
    assert fetched.model == "second-model"
