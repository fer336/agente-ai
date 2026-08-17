from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / `.env`.

    Postgres and Redis are configured as discrete fields (host/port/credentials)
    so the app can be run directly on the user's own server, plus a derived
    single-URL form for convenience (SQLAlchemy/Redis client constructors).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    #: Empty by default (no real LLM/audio provider wired yet, PRD.md §33 —
    #: a later change) — still stamped on every `AgentRun.model` as
    #: whatever is configured, matching every other still-unconfigured
    #: integration in this file (e.g. `ycloud_api_key`).
    openai_model: str = ""

    #: PRD.md §68/§50's documented names/defaults — how many same
    #: `source`+`error_type` errors within how many seconds counts as
    #: "repeated" rather than "aislado" for `ErrorService.classify`'s
    #: severity escalation (PRD.md §46).
    alert_timeout_threshold_count: int = 5
    alert_timeout_threshold_window_seconds: int = 120

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
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
