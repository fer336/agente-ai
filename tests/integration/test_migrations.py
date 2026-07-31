"""Integration test: `alembic upgrade head` against a real Postgres instance
(design Testing Strategy: "Integration | Alembic `upgrade head` | runs against
docker-compose Postgres in CI/local").

Requires a reachable Postgres (`docker-compose up -d postgres`, per the tasks
doc's Unit 2 runtime harness). Not reachable in this sandbox — the fixture
below skips gracefully rather than erroring, but runs for real once Postgres
is up.
"""

import socket

import pytest
from alembic import command
from alembic.config import Config

from app.config.settings import get_settings


def _alembic_config() -> Config:
    settings = get_settings()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


@pytest.fixture
def postgres_reachable() -> None:
    settings = get_settings()
    try:
        with socket.create_connection(
            (settings.postgres_host, settings.postgres_port), timeout=1
        ):
            return
    except OSError as exc:
        pytest.skip(f"Postgres not reachable for migration test: {exc}")


def test_alembic_upgrade_head_applies_cleanly(postgres_reachable: None) -> None:
    command.upgrade(_alembic_config(), "head")
