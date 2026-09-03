from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / `.env`.

    Postgres and Redis are configured as discrete fields (host/port/credentials)
    so the app can be run directly on the user's own server, plus a derived
    single-URL form for convenience (SQLAlchemy/Redis client constructors).
    """

    #: Two candidate paths, not one: local/dev runs read `.env` from the cwd;
    #: the production Swarm stack (`docker-stack.yml`) mounts the config as a
    #: Docker secret file at `/run/secrets/backend.env` instead — a plain
    #: env-var injection isn't how Swarm secrets work. Whichever path exists
    #: on disk is used; a missing one is silently skipped by pydantic-settings,
    #: so this is safe in both environments without an if/else.
    model_config = SettingsConfigDict(
        env_file=(".env", "/run/secrets/backend.env"), extra="ignore"
    )

    app_host: str = "0.0.0.0"
    app_port: int = 8000

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "clinic_ai_agent"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None

    ycloud_api_url: str = ""
    ycloud_api_key: str = ""
    ycloud_webhook_secret: str = ""
    ycloud_whatsapp_number: str = ""

    dentalink_api_url: str = "https://api.dentalink.healthatom.com/api"
    dentalink_access_token: str = ""
    dentalink_timeout_seconds: float = 15
    # Not PRD-named env vars (PRD.md §68 only lists the three above) — added
    # to bridge AppointmentGateway's existing Protocol signature (no branch/
    # chair/sucursal parameter) against Dentalink's required request fields
    # for a single-clinic MVP (PRD.md intro: "diseñado exclusivamente para
    # una clínica específica"). See the DentalinkGateway change's report.
    dentalink_default_branch_id: str = ""
    dentalink_default_chair_id: str = ""
    dentalink_default_duration_minutes: int = 30

    message_debounce_seconds: int = 6
    #: PRD.md §68's documented name/default — how long a `PendingAction`
    #: proposal stays confirmable before the (not-yet-built) expiry worker
    #: would expire it (PRD.md §16.1).
    appointment_confirmation_timeout_seconds: int = 120

    #: PRD.md §68's documented name/default — stamped on every `AgentRun`
    #: (PRD.md §39) so a prompt/behavior change can be correlated with the
    #: runs it affected.
    prompt_version: str = "agent-system-v0.1.0"
    #: Model identifier stamped on every `AgentRun.model` (PRD.md §68's
    #: documented name/default) AND sent as the real `model` field in every
    #: `llm_api_url` request — this codebase's LLM provider is an
    #: OpenAI-compatible gateway (9Router), not literally OpenAI, but the
    #: field name follows the PRD's original naming to avoid churn.
    openai_model: str = ""
    #: OpenAI-compatible chat-completions endpoint (e.g. a self-hosted
    #: 9Router instance) — base URL including `/v1`, no trailing slash
    #: required. Empty by default (falls back to `FakeLLMProvider`, see
    #: `app.api.dependencies.gateways.get_llm_provider`).
    llm_api_url: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = 20

    #: PRD.md §68/§50's documented names/defaults — how many same
    #: `source`+`error_type` errors within how many seconds counts as
    #: "repeated" rather than "aislado" for `ErrorService.classify`'s
    #: severity escalation (PRD.md §46).
    alert_timeout_threshold_count: int = 5
    alert_timeout_threshold_window_seconds: int = 120

    #: Audio/transcription pipeline (PRD.md §24, §68, §74.7). PRD.md §68's
    #: template names this `OPENAI_TRANSCRIPTION_MODEL` — this codebase's
    #: chosen provider is Groq instead (user decision), so the env var
    #: names below follow Groq's own naming, not the PRD template verbatim.
    groq_api_key: str = ""
    groq_api_url: str = "https://api.groq.com/openai/v1"
    groq_transcription_model: str = "whisper-large-v3-turbo"

    audio_max_size_bytes: int = 16_777_216
    audio_max_duration_seconds: int = 180
    audio_download_timeout_seconds: float = 20
    audio_transcription_timeout_seconds: float = 45
    audio_allowed_mime_types: str = "audio/ogg,audio/mpeg,audio/mp4,audio/aac"
    #: PRD.md §24.3: "Eliminar el temporal después de transcribir o fallar
    #: definitivamente" is a hard security requirement, not an optional
    #: behavior — `TranscribeAudioUseCase` always deletes its temp file
    #: unconditionally and does not read this setting. Kept only so
    #: `.env.example` documents the PRD-named var; wiring a real opt-out
    #: would contradict §74.7's "no almacenar permanentemente" mandate.
    audio_delete_after_processing: bool = True
    audio_rate_limit_per_conversation_per_minute: int = 5
    #: Extra hostnames `SecureMediaDownloader` may fetch from, beyond
    #: `ycloud_api_url`'s own host (comma-separated) — a vendor's media CDN
    #: is often a different domain than its REST API.
    ycloud_media_allowed_hosts: str = ""

    #: Admin panel (PRD.md §44, §74.3). Empty by default, same convention as
    #: every other still-unconfigured secret in this file — a deploy MUST
    #: set a real secret before the panel is reachable with a valid signed
    #: session (an empty secret still signs/verifies internally-consistently,
    #: it's just a guessable one, so `Settings` doesn't refuse to start on
    #: it — same posture as `ycloud_webhook_secret`).
    admin_session_secret: str = ""
    admin_session_ttl_seconds: int = 3600
    #: PRD.md §61's internal evaluation endpoint (`POST /internal/eval/chat`)
    #: — PRD.md §74.3's last line requires it "deshabilitado en producción
    #: salvo necesidad expresa, autenticación fuerte y restricción de red",
    #: hence off by default. Even when enabled it still requires a valid
    #: admin session (see `app.api.routes.internal_eval`) — the network
    #: restriction half of that requirement is a deployment/infra concern
    #: this flag cannot enforce by itself.
    internal_eval_enabled: bool = False

    #: Incident deduplication + Telegram + Linear (PRD.md §47-51, Etapa 9's
    #: remaining scope). Empty by default, same convention as every other
    #: still-unconfigured secret in this file — `TelegramAlertNotifier`/
    #: `LinearIncidentGateway` are Fake-wired by default in DI (no live
    #: Telegram bot or Linear workspace credentials in this environment).
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    linear_api_key: str = ""
    #: Linear issue creation is scoped to one team — required to build a
    #: `LinearIncidentGateway.create_issue` GraphQL mutation.
    linear_team_id: str = ""

    #: PRD.md §50's suggested defaults — distinct from `alert_timeout_
    #: threshold_count`/`_window_seconds` above (those decide WARNING→ERROR
    #: severity escalation per §46; these decide ERROR→"create/update a
    #: Linear issue" per §46's "Linear podrá crearse si el problema supera
    #: el umbral definido").
    incident_threshold_count: int = 10
    incident_threshold_window_seconds: int = 300
    #: PRD.md §50 — suppresses a duplicate Telegram notification for the
    #: same incident fingerprint within this many seconds, so a burst of
    #: identical errors sends one alert, not one per error.
    telegram_alert_cooldown_seconds: int = 900

    #: Conversational memory module (no PRD.md section number — this
    #: session's own brief). "10 a 20 mensajes, configurable" — 15 as a
    #: middle-of-range default for `MemoryService`'s recent-window layer.
    memory_recent_window_size: int = 15
    #: How many new, not-yet-compacted messages accumulate for a contact
    #: before `app.workers.memory_tasks.compact_stale_contact_memories`
    #: (a one-poll-tick sweep, not scheduler-wired yet — same accepted gap
    #: as `process_pending_audio_jobs`/`check_incident_recovery`) compacts it.
    memory_compaction_message_threshold: int = 20
    #: TTL for `MemoryService`'s Redis cache of a contact's compacted
    #: summary — a cache miss/expiry always falls back to PostgreSQL, never
    #: a permanent loss (PostgreSQL is this module's source of truth).
    memory_cache_ttl_seconds: int = 3600

    @computed_field  # type: ignore[prop-decorator]
    @property
    def audio_allowed_mime_types_set(self) -> frozenset[str]:
        return frozenset(
            value.strip() for value in self.audio_allowed_mime_types.split(",") if value.strip()
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def checkpointer_database_url(self) -> str:
        """DSN for the LangGraph checkpointer's own connection pool.

        `psycopg`/`psycopg_pool` (what `create_postgres_checkpointer_pool`
        builds — deliberately separate from the SQLAlchemy asyncpg engine)
        does not understand SQLAlchemy's `+asyncpg` dialect suffix in
        `database_url` — it fails every connection attempt with "missing
        '=' after ... in connection info string" and the pool times out.
        Plain `postgresql://` is what psycopg's own DSN parser expects.
        """
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
