import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime

from redis.asyncio import Redis

from app.domain.entities.runtime_agent_config import RuntimeAgentConfig
from app.domain.repositories.runtime_config_repository import RuntimeConfigRepository

logger = logging.getLogger(__name__)

_CACHE_KEY = "runtime_agent_config"

#: Matches every other `..._repositories_provider` in this codebase (e.g.
#: `IngestMessageUseCase.repositories_provider`) — an async-context-manager
#: factory, so a fresh session is opened per call rather than held open for
#: this service's lifetime.
RuntimeConfigRepositoryProvider = Callable[
    [], AbstractAsyncContextManager[RuntimeConfigRepository]
]


class RuntimeConfigService:
    """Redis-cache-in-front-of-Postgres live source for agent runtime
    config (model, temperature, debounce, prompts) — this session's own
    brief, no PRD.md section number.

    A DB row alone does not make a setting "runtime": every consumer
    (`OpenAICompatibleLLMProvider`, `IngestMessageUseCase`) must call
    `get_config()` fresh on each use rather than baking a value into a
    constructor. `cache_ttl_seconds` bounds how long an admin edit takes to
    actually apply everywhere (default 10s) — short enough to feel "live",
    long enough that `classify_intent` (called on every single turn) isn't
    a Postgres round-trip most of the time. Same Redis-optional,
    Postgres-is-source-of-truth posture as `MemoryService`'s own cache: any
    Redis failure logs a warning and falls through to Postgres, never
    raises.
    """

    def __init__(
        self,
        repositories_provider: RuntimeConfigRepositoryProvider,
        default_config: Callable[[], RuntimeAgentConfig],
        redis_client: Redis | None = None,
        cache_ttl_seconds: int = 10,
    ) -> None:
        self._repositories_provider = repositories_provider
        self._default_config = default_config
        self._redis_client = redis_client
        self._cache_ttl_seconds = cache_ttl_seconds

    async def get_config(self) -> RuntimeAgentConfig:
        cached = await self._read_cache()
        if cached is not None:
            return cached

        async with self._repositories_provider() as repository:
            config = await repository.get()
        if config is None:
            config = self._default_config()
        await self._write_cache(config)
        return config

    async def save_config(self, config: RuntimeAgentConfig) -> None:
        async with self._repositories_provider() as repository:
            await repository.save(config)
        await self.invalidate_cache()

    async def invalidate_cache(self) -> None:
        if self._redis_client is None:
            return
        try:
            await self._redis_client.delete(_CACHE_KEY)
        except Exception:  # noqa: BLE001 - cache invalidation must never break a write path
            logger.warning("runtime_config_service.invalidate_cache redis_error", exc_info=True)

    async def _read_cache(self) -> RuntimeAgentConfig | None:
        if self._redis_client is None:
            return None
        try:
            raw = await self._redis_client.get(_CACHE_KEY)
        except Exception:  # noqa: BLE001 - Postgres is the source of truth, cache is optional
            logger.warning("runtime_config_service.get_config redis_read_error", exc_info=True)
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        payload = json.loads(raw)
        return RuntimeAgentConfig(
            id=payload["id"],
            model=payload["model"],
            temperature=payload["temperature"],
            debounce_seconds=payload["debounce_seconds"],
            classify_intent_prompt=payload["classify_intent_prompt"],
            extract_information_prompt=payload["extract_information_prompt"],
            generate_response_prompt=payload["generate_response_prompt"],
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            updated_by=payload["updated_by"],
        )

    async def _write_cache(self, config: RuntimeAgentConfig) -> None:
        if self._redis_client is None:
            return
        payload = {
            "id": config.id,
            "model": config.model,
            "temperature": config.temperature,
            "debounce_seconds": config.debounce_seconds,
            "classify_intent_prompt": config.classify_intent_prompt,
            "extract_information_prompt": config.extract_information_prompt,
            "generate_response_prompt": config.generate_response_prompt,
            "updated_at": config.updated_at.isoformat(),
            "updated_by": config.updated_by,
        }
        try:
            await self._redis_client.set(
                _CACHE_KEY, json.dumps(payload), ex=self._cache_ttl_seconds
            )
        except Exception:  # noqa: BLE001 - a failed cache write must never break a read path
            logger.warning("runtime_config_service.get_config redis_write_error", exc_info=True)
