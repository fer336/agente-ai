from functools import lru_cache

from app.api.dependencies.gateways import get_agent_invoker
from app.api.dependencies.redis import get_debounce_tracker, get_shared_redis_client
from app.api.dependencies.repositories import open_sqlalchemy_message_repositories
from app.application.messages.ingest_message import IngestMessageUseCase
from app.config.settings import get_settings


@lru_cache
def get_ingest_message_use_case() -> IngestMessageUseCase:
    """FastAPI dependency providing the `IngestMessageUseCase` singleton.

    MUST be `@lru_cache`d (a process-level singleton), not constructed
    fresh per request — see `IngestMessageUseCase`'s own docstring for why:
    its per-conversation debounce/grouping state must persist across HTTP
    requests for the same running process, or message grouping silently
    breaks (every request would start a fresh, empty accumulator).
    """
    settings = get_settings()
    return IngestMessageUseCase(
        repositories_provider=open_sqlalchemy_message_repositories,
        debounce_tracker=get_debounce_tracker(),
        redis_client=get_shared_redis_client(),
        agent_invoker=get_agent_invoker(),
        debounce_seconds=settings.message_debounce_seconds,
    )
