from datetime import UTC, datetime
from functools import lru_cache

from app.api.dependencies.redis import get_shared_redis_client
from app.api.dependencies.repositories import open_sqlalchemy_runtime_config_repository
from app.application.config.runtime_config_service import RuntimeConfigService
from app.config.settings import get_settings
from app.domain.entities.runtime_agent_config import RUNTIME_AGENT_CONFIG_ID, RuntimeAgentConfig
from app.infrastructure.llm.openai_compatible_llm_provider import (
    DEFAULT_CLASSIFY_INTENT_PROMPT,
    DEFAULT_EXTRACT_INFORMATION_PROMPT,
    DEFAULT_GENERATE_RESPONSE_PROMPT,
)


#: `RuntimeConfigService`'s fallback when no admin has ever saved a
#: `RuntimeAgentConfig` row yet — mirrors what every value used to be
#: frozen to before this became admin-editable (this session's own brief).
def _default_runtime_agent_config() -> RuntimeAgentConfig:
    settings = get_settings()
    return RuntimeAgentConfig(
        id=RUNTIME_AGENT_CONFIG_ID,
        model=settings.openai_model,
        temperature=0.0,
        debounce_seconds=settings.message_debounce_seconds,
        classify_intent_prompt=DEFAULT_CLASSIFY_INTENT_PROMPT,
        extract_information_prompt=DEFAULT_EXTRACT_INFORMATION_PROMPT,
        generate_response_prompt=DEFAULT_GENERATE_RESPONSE_PROMPT,
        updated_at=datetime.now(UTC),
        updated_by="system-default",
    )


@lru_cache
def get_runtime_config_service() -> RuntimeConfigService:
    """FastAPI dependency providing the process-lifetime `RuntimeConfigService`.

    `@lru_cache`d like every other DI singleton in this codebase — but
    unlike those, the object itself holds no frozen config VALUE, only a
    reference to how to fetch one live (repository provider + Redis
    cache). See `RuntimeConfigService`'s own docstring.
    """
    return RuntimeConfigService(
        repositories_provider=open_sqlalchemy_runtime_config_repository,
        default_config=_default_runtime_agent_config,
        redis_client=get_shared_redis_client(),
    )
