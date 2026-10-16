from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[3] / "entrypoint.sh"

# Fake `uv`: logs its args; `alembic current` consults a counter file so the
# first FAKE_NOT_READY_CALLS calls fail/print a stale revision, then it is at head.
FAKE_UV = """#!/bin/sh
echo "$*" >> "$FAKE_DIR/calls.log"
case "$*" in
  *"alembic current"*)
    n=$(cat "$FAKE_DIR/counter" 2>/dev/null || echo 0)
    n=$((n + 1))
    echo "$n" > "$FAKE_DIR/counter"
    if [ "$n" -le "${FAKE_NOT_READY_CALLS:-0}" ]; then
      if [ "$n" -eq 1 ]; then
        echo "database not up yet" >&2
        exit 1
      fi
      echo "abc123"
      exit 0
    fi
    echo "def456 (head)"
    ;;
esac
exit 0
"""


@pytest.fixture
def fake_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    return tmp_path


def _run(
    fake_dir: Path, role: str | None, **extra: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    env = {
        "PATH": f"{fake_dir / 'bin'}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake_dir),
        **extra,
    }
    if role is not None:
        env["APP_ROLE"] = role
    result = subprocess.run(
        ["sh", str(ENTRYPOINT)],
        env=env,
        cwd=fake_dir,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    log = fake_dir / "calls.log"
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def _has(calls: list[str], fragment: str) -> bool:
    return any(fragment in call for call in calls)


def test_admin_waits_until_schema_is_at_head_then_starts(fake_dir: Path) -> None:
    result, calls = _run(
        fake_dir,
        "admin",
        FAKE_NOT_READY_CALLS="2",
        ADMIN_SCHEMA_POLL_SECONDS="1",
        ADMIN_SCHEMA_WAIT_SECONDS="30",
    )
    assert result.returncode == 0, result.stderr
    assert sum("alembic current" in c for c in calls) == 3
    assert "uvicorn" in calls[-1]
    assert "waiting" in result.stdout.lower()
    assert "ready" in result.stdout.lower()


def test_admin_starts_immediately_when_already_at_head(fake_dir: Path) -> None:
    result, calls = _run(fake_dir, "admin", FAKE_NOT_READY_CALLS="0")
    assert result.returncode == 0, result.stderr
    assert sum("alembic current" in c for c in calls) == 1
    assert "uvicorn" in calls[-1]


def test_admin_times_out_with_exit_1_when_never_ready(fake_dir: Path) -> None:
    result, calls = _run(
        fake_dir,
        "admin",
        FAKE_NOT_READY_CALLS="1000",
        ADMIN_SCHEMA_POLL_SECONDS="1",
        ADMIN_SCHEMA_WAIT_SECONDS="2",
    )
    assert result.returncode == 1
    assert "migration head" in result.stderr
    assert not _has(calls, "uvicorn")


def test_admin_never_runs_migrations(fake_dir: Path) -> None:
    _, calls = _run(fake_dir, "admin")
    assert not _has(calls, "alembic upgrade")


@pytest.mark.parametrize("role", ["bot", "all", None])
def test_bot_all_and_unset_migrate_then_start_without_waiting(
    fake_dir: Path, role: str | None
) -> None:
    result, calls = _run(fake_dir, role)
    assert result.returncode == 0, result.stderr
    assert not _has(calls, "alembic current")
    assert "alembic upgrade head" in calls[0]
    assert "uvicorn" in calls[1]
    assert len(calls) == 2


def test_unknown_role_exits_1_without_calling_uv(fake_dir: Path) -> None:
    result, calls = _run(fake_dir, "nope")
    assert result.returncode == 1
    assert "unknown APP_ROLE" in result.stderr
    assert calls == []
