from app.config.settings import Settings, get_settings


def test_settings_uses_defaults_and_derives_urls_when_no_env_vars(monkeypatch):
    for var in (
        "APP_HOST",
        "APP_PORT",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_host == "0.0.0.0"
    assert settings.app_port == 8000
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.database_url == "postgresql+asyncpg://postgres:postgres@localhost:5432/clinic_ai_agent"
    assert settings.redis_host == "localhost"
    assert settings.redis_port == 6379
    assert settings.redis_password is None
    assert settings.redis_url == "redis://localhost:6379/0"


def test_settings_reads_discrete_fields_from_env_and_derives_matching_urls(monkeypatch):
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_USER", "clinic")
    monkeypatch.setenv("POSTGRES_PASSWORD", "s3cret")
    monkeypatch.setenv("POSTGRES_DB", "clinic_prod")
    monkeypatch.setenv("REDIS_HOST", "cache.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 9000
    assert settings.database_url == "postgresql+asyncpg://clinic:s3cret@db.internal:5433/clinic_prod"
    assert settings.redis_url == "redis://cache.internal:6380/0"


def test_get_settings_returns_the_same_cached_instance():
    assert get_settings() is get_settings()


def test_redis_url_includes_password_when_redis_password_is_set(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "cache.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_PASSWORD", "s3cret")

    settings = Settings(_env_file=None)

    assert settings.redis_password == "s3cret"
    assert settings.redis_url == "redis://:s3cret@cache.internal:6380/0"


def test_settings_reads_redis_password_from_env(monkeypatch):
    monkeypatch.setenv("REDIS_PASSWORD", "env-pass")

    settings = Settings(_env_file=None)

    assert settings.redis_password == "env-pass"


def test_settings_defaults_ycloud_and_debounce_fields_when_no_env_vars(monkeypatch):
    for var in (
        "YCLOUD_API_URL",
        "YCLOUD_API_KEY",
        "YCLOUD_WEBHOOK_SECRET",
        "YCLOUD_WHATSAPP_NUMBER",
        "MESSAGE_DEBOUNCE_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.ycloud_api_url == ""
    assert settings.ycloud_api_key == ""
    assert settings.ycloud_webhook_secret == ""
    assert settings.ycloud_whatsapp_number == ""
    assert settings.message_debounce_seconds == 6


def test_settings_reads_ycloud_and_debounce_fields_from_env(monkeypatch):
    monkeypatch.setenv("YCLOUD_API_URL", "https://api.ycloud.com")
    monkeypatch.setenv("YCLOUD_API_KEY", "yc-key")
    monkeypatch.setenv("YCLOUD_WEBHOOK_SECRET", "yc-secret")
    monkeypatch.setenv("YCLOUD_WHATSAPP_NUMBER", "+5491100000001")
    monkeypatch.setenv("MESSAGE_DEBOUNCE_SECONDS", "10")

    settings = Settings(_env_file=None)

    assert settings.ycloud_api_url == "https://api.ycloud.com"
    assert settings.ycloud_api_key == "yc-key"
    assert settings.ycloud_webhook_secret == "yc-secret"
    assert settings.ycloud_whatsapp_number == "+5491100000001"
    assert settings.message_debounce_seconds == 10


def test_settings_defaults_appointment_confirmation_timeout_when_no_env_var(monkeypatch):
    monkeypatch.delenv("APPOINTMENT_CONFIRMATION_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.appointment_confirmation_timeout_seconds == 120


def test_settings_reads_appointment_confirmation_timeout_from_env(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_CONFIRMATION_TIMEOUT_SECONDS", "90")

    settings = Settings(_env_file=None)

    assert settings.appointment_confirmation_timeout_seconds == 90


def test_settings_defaults_dentalink_fields_when_no_env_vars(monkeypatch):
    for var in (
        "DENTALINK_API_URL",
        "DENTALINK_ACCESS_TOKEN",
        "DENTALINK_TIMEOUT_SECONDS",
        "DENTALINK_DEFAULT_BRANCH_ID",
        "DENTALINK_DEFAULT_CHAIR_ID",
        "DENTALINK_DEFAULT_DURATION_MINUTES",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.dentalink_api_url == "https://api.dentalink.healthatom.com/api"
    assert settings.dentalink_access_token == ""
    assert settings.dentalink_timeout_seconds == 15
    assert settings.dentalink_default_branch_id == ""
    assert settings.dentalink_default_chair_id == ""
    assert settings.dentalink_default_duration_minutes == 30


def test_settings_reads_dentalink_fields_from_env(monkeypatch):
    monkeypatch.setenv("DENTALINK_API_URL", "https://dentalink.example.com/api")
    monkeypatch.setenv("DENTALINK_ACCESS_TOKEN", "dl-token")
    monkeypatch.setenv("DENTALINK_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("DENTALINK_DEFAULT_BRANCH_ID", "1")
    monkeypatch.setenv("DENTALINK_DEFAULT_CHAIR_ID", "5")
    monkeypatch.setenv("DENTALINK_DEFAULT_DURATION_MINUTES", "45")

    settings = Settings(_env_file=None)

    assert settings.dentalink_api_url == "https://dentalink.example.com/api"
    assert settings.dentalink_access_token == "dl-token"
    assert settings.dentalink_timeout_seconds == 20
    assert settings.dentalink_default_branch_id == "1"
    assert settings.dentalink_default_chair_id == "5"
    assert settings.dentalink_default_duration_minutes == 45


def test_settings_defaults_observability_fields_when_no_env_vars(monkeypatch):
    for var in ("PROMPT_VERSION", "OPENAI_MODEL"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.prompt_version == "agent-system-v0.1.0"
    assert settings.openai_model == ""


def test_settings_reads_observability_fields_from_env(monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "agent-system-v0.2.0")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    settings = Settings(_env_file=None)

    assert settings.prompt_version == "agent-system-v0.2.0"
    assert settings.openai_model == "gpt-4o-mini"


def test_settings_defaults_alert_threshold_fields_when_no_env_vars(monkeypatch):
    for var in ("ALERT_TIMEOUT_THRESHOLD_COUNT", "ALERT_TIMEOUT_THRESHOLD_WINDOW_SECONDS"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.alert_timeout_threshold_count == 5
    assert settings.alert_timeout_threshold_window_seconds == 120


def test_settings_reads_alert_threshold_fields_from_env(monkeypatch):
    monkeypatch.setenv("ALERT_TIMEOUT_THRESHOLD_COUNT", "3")
    monkeypatch.setenv("ALERT_TIMEOUT_THRESHOLD_WINDOW_SECONDS", "60")

    settings = Settings(_env_file=None)

    assert settings.alert_timeout_threshold_count == 3
    assert settings.alert_timeout_threshold_window_seconds == 60
