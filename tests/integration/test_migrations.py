"""Integration test: `alembic upgrade head` against a real Postgres instance
(design Testing Strategy: "Integration | Alembic `upgrade head` | runs against
docker-compose Postgres in CI/local").

Requires both a reachable Postgres AND `integration_db_tests_enabled` set
(`postgres_reachable`'s own docstring explains why) — the fixture skips
gracefully otherwise, whether that's because Postgres genuinely isn't
reachable or because the opt-in flag isn't set.
"""

import socket

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config.settings import get_settings


def _alembic_config() -> Config:
    settings = get_settings()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


@pytest.fixture
def postgres_reachable() -> None:
    # Same explicit opt-in as `tests/integration/conftest.py`'s `db_session`
    # fixture (`INTEGRATION_DB_TESTS_ENABLED`) — `alembic upgrade head`
    # doesn't drop anything, but it still WRITES to whatever `database_url`
    # resolves to, unconditionally, the moment Postgres is reachable. Seen
    # live: this test ran against real production (a `.env` pointing there,
    # same as `db_session`'s incident) during ordinary local development,
    # applying a migration outside the actual deploy pipeline entirely —
    # harmless that specific time only because the migration itself was
    # a safe column-nullability relax, not because anything here stopped it.
    settings = get_settings()
    if not settings.integration_db_tests_enabled:
        pytest.skip(
            "integration_db_tests_enabled is not set — this test runs `alembic upgrade "
            "head` against whatever database_url resolves to, so it refuses to run unless "
            "explicitly opted into (set INTEGRATION_DB_TESTS_ENABLED=true, never in a "
            "persistent .env that also holds real credentials)."
        )
    try:
        with socket.create_connection(
            (settings.postgres_host, settings.postgres_port), timeout=1
        ):
            return
    except OSError as exc:
        pytest.skip(f"Postgres not reachable for migration test: {exc}")


def test_alembic_upgrade_head_applies_cleanly(postgres_reachable: None) -> None:
    command.upgrade(_alembic_config(), "head")


def test_every_revision_id_fits_the_alembic_version_column() -> None:
    # Regression: `alembic_version.version_num` is `VARCHAR(32)` in every
    # environment this project has ever migrated (see 0001_base) — a
    # revision id longer than that makes alembic's own final `UPDATE
    # alembic_version SET version_num=...` step fail with
    # `StringDataRightTruncationError`, rolling back the ENTIRE migration
    # (including whatever schema change it made) and crashing the
    # container outright (`entrypoint.sh` runs under `set -eu`). Seen
    # live: shipped as v0.30.1, took production down harder than the bug
    # the migration was meant to fix. No DB needed — this only inspects
    # the migration files themselves, so it always runs in CI.
    script = ScriptDirectory.from_config(_alembic_config())
    too_long = [
        revision.revision
        for revision in script.walk_revisions()
        if len(revision.revision) > 32
    ]
    assert not too_long, f"revision id(s) exceed alembic_version's VARCHAR(32): {too_long}"
