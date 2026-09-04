from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from app.application.config.runtime_config_service import RuntimeConfigService
from app.domain.entities.runtime_agent_config import RuntimeAgentConfig
from app.domain.repositories.runtime_config_repository import RuntimeConfigRepository
from app.infrastructure.database.fake_runtime_config_repository import (
    FakeRuntimeConfigRepository,
)
from tests.fixtures.fake_redis import InMemoryFakeRedis

_NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


class _BrokenRedis:
    async def get(self, name: str) -> bytes | None:
        raise ConnectionError("redis unreachable")

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        raise ConnectionError("redis unreachable")

    async def delete(self, name: str) -> None:
        raise ConnectionError("redis unreachable")


def _config(**overrides: object) -> RuntimeAgentConfig:
    defaults: dict[str, object] = {
        "id": "default",
        "model": "gemini/gemini-3.7-flash",
        "temperature": 0.0,
        "debounce_seconds": 6,
        "classify_intent_prompt": "classify this",
        "extract_information_prompt": "extract {required_fields}",
        "generate_response_prompt": "respond to {intent} with {collected_data}",
        "updated_at": _NOW,
        "updated_by": "admin-1",
    }
    defaults.update(overrides)
    return RuntimeAgentConfig(**defaults)  # type: ignore[arg-type]


def _default_config() -> RuntimeAgentConfig:
    return _config(id="default", model="fallback-model")


def _build_service(
    repository: RuntimeConfigRepository | None = None,
    redis_client=None,
    cache_ttl_seconds: int = 10,
) -> tuple[RuntimeConfigService, FakeRuntimeConfigRepository]:
    repository = repository or FakeRuntimeConfigRepository()

    @asynccontextmanager
    async def open_repository() -> AsyncIterator[RuntimeConfigRepository]:
        yield repository

    service = RuntimeConfigService(
        repositories_provider=open_repository,
        default_config=_default_config,
        redis_client=redis_client,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    return service, repository  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_get_config_returns_the_default_when_no_row_exists():
    service, _ = _build_service()

    config = await service.get_config()

    assert config.model == "fallback-model"


@pytest.mark.asyncio
async def test_get_config_returns_the_saved_row_when_one_exists():
    repository = FakeRuntimeConfigRepository()
    await repository.save(_config(model="gpt-real"))
    service, _ = _build_service(repository=repository)

    config = await service.get_config()

    assert config.model == "gpt-real"


@pytest.mark.asyncio
async def test_get_config_cache_miss_populates_the_cache():
    repository = FakeRuntimeConfigRepository()
    await repository.save(_config(model="gpt-real"))
    redis = InMemoryFakeRedis()
    service, _ = _build_service(repository=repository, redis_client=redis)

    await service.get_config()

    assert await redis.get("runtime_agent_config") is not None


@pytest.mark.asyncio
async def test_get_config_cache_hit_never_touches_the_repository():
    repository = FakeRuntimeConfigRepository()
    await repository.save(_config(model="original"))
    redis = InMemoryFakeRedis()
    service, _ = _build_service(repository=repository, redis_client=redis)
    await service.get_config()  # warms the cache

    # Mutate the repository directly without invalidating the cache.
    await repository.save(_config(model="changed-behind-the-cache"))

    config = await service.get_config()

    assert config.model == "original"


@pytest.mark.asyncio
async def test_get_config_falls_back_to_repository_when_redis_is_down():
    repository = FakeRuntimeConfigRepository()
    await repository.save(_config(model="from-postgres"))
    service, _ = _build_service(repository=repository, redis_client=_BrokenRedis())

    config = await service.get_config()

    assert config.model == "from-postgres"


@pytest.mark.asyncio
async def test_save_config_persists_and_invalidates_the_cache():
    redis = InMemoryFakeRedis()
    service, repository = _build_service(redis_client=redis)
    await service.get_config()  # warms the cache with the default

    await service.save_config(_config(model="admin-edited"))

    assert await redis.get("runtime_agent_config") is None
    saved = await repository.get()
    assert saved is not None
    assert saved.model == "admin-edited"

    config = await service.get_config()
    assert config.model == "admin-edited"


@pytest.mark.asyncio
async def test_invalidate_cache_with_no_redis_client_is_a_noop():
    service, _ = _build_service(redis_client=None)

    await service.invalidate_cache()
