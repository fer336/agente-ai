from functools import lru_cache

from app.api.dependencies.gateways import (
    get_agent_invoker,
    get_media_downloader,
    get_media_gateway,
    get_messaging_gateway,
    get_transcription_gateway,
)
from app.api.dependencies.redis import get_debounce_tracker, get_shared_redis_client
from app.api.dependencies.repositories import (
    open_sqlalchemy_message_repositories,
    open_sqlalchemy_transcription_repositories,
)
from app.application.audio.transcribe_audio import TranscribeAudioUseCase
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
        audio_rate_limit_per_minute=settings.audio_rate_limit_per_conversation_per_minute,
    )


@lru_cache
def get_transcribe_audio_use_case() -> TranscribeAudioUseCase:
    """FastAPI dependency providing the `TranscribeAudioUseCase` singleton
    (PRD.md §24.1, Etapa 9.1).

    Not called from any HTTP route — the not-yet-built worker entrypoint
    (`app.workers.audio_tasks.process_pending_audio_jobs`'s eventual
    caller, PRD.md §65) is meant to use this. Exposed here as the one
    production-DI wiring point so that entrypoint doesn't need to hand-
    assemble every dependency itself.
    """
    settings = get_settings()
    return TranscribeAudioUseCase(
        repositories_provider=open_sqlalchemy_transcription_repositories,
        media_gateway=get_media_gateway(),
        media_downloader=get_media_downloader(),
        transcription_gateway=get_transcription_gateway(),
        messaging_gateway=get_messaging_gateway(),
        ingest_message_use_case=get_ingest_message_use_case(),
        allowed_mime_types=settings.audio_allowed_mime_types_set,
        max_size_bytes=settings.audio_max_size_bytes,
        max_duration_seconds=settings.audio_max_duration_seconds,
        transcription_timeout_seconds=settings.audio_transcription_timeout_seconds,
        provider_name="groq",
        model_name=settings.groq_transcription_model,
    )
