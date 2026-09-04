from datetime import UTC, datetime

import pytest

from app.domain.entities.runtime_agent_config import RuntimeAgentConfig
from app.domain.repositories.runtime_config_repository import RuntimeConfigRepository
from app.infrastructure.database.fake_runtime_config_repository import (
    FakeRuntimeConfigRepository,
)

_NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


def _config(model: str = "gemini/gemini-3.7-flash") -> RuntimeAgentConfig:
    return RuntimeAgentConfig(
        id="default",
        model=model,
        temperature=0.0,
        debounce_seconds=6,
        classify_intent_prompt="classify this",
        extract_information_prompt="extract {required_fields}",
        generate_response_prompt="respond to {intent} with {collected_data}",
        updated_at=_NOW,
        updated_by="admin-1",
    )


@pytest.mark.asyncio
async def test_get_returns_none_by_default():
    repository = FakeRuntimeConfigRepository()

    assert await repository.get() is None


@pytest.mark.asyncio
async def test_get_returns_the_preset_config():
    repository = FakeRuntimeConfigRepository(_config())

    config = await repository.get()

    assert config is not None
    assert config.model == "gemini/gemini-3.7-flash"


@pytest.mark.asyncio
async def test_save_then_get_round_trips():
    repository = FakeRuntimeConfigRepository()

    await repository.save(_config(model="admin-edited"))

    config = await repository.get()
    assert config is not None
    assert config.model == "admin-edited"


def test_fake_runtime_config_repository_satisfies_runtime_config_repository_protocol():
    assert isinstance(FakeRuntimeConfigRepository(), RuntimeConfigRepository)
