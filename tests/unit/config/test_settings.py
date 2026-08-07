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
