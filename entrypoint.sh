#!/bin/sh
set -eu

# APP_ROLE selects what this container serves (see app/main.py): bot, admin or
# all. Only the roles that own the database schema run migrations, so the admin
# service never races the bot on alembic_version.
role="${APP_ROLE:-all}"

case "$role" in
  bot | all)
    uv run --no-sync python -m alembic upgrade head
    ;;
  admin)
    echo "APP_ROLE=admin: skipping alembic migrations (owned by the bot service)"
    # After a release that adds a migration the bot service may still be
    # upgrading; do not serve on a stale schema. `alembic current` prints
    # "<rev> (head)" once the database is at the head revision. Any failure
    # (e.g. database not up yet) counts as not ready.
    wait_limit="${ADMIN_SCHEMA_WAIT_SECONDS:-300}"
    poll="${ADMIN_SCHEMA_POLL_SECONDS:-3}"
    waited=0
    announced=0
    while :; do
      current="$(uv run --no-sync python -m alembic current 2>/dev/null || true)"
      case "$current" in
        *"(head)"*) break ;;
      esac
      if [ "$announced" -eq 0 ]; then
        echo "APP_ROLE=admin: waiting for the database schema to reach the migration head (up to ${wait_limit}s)"
        announced=1
      fi
      if [ "$waited" -ge "$wait_limit" ]; then
        echo "entrypoint: database schema not at the migration head after ${wait_limit}s" >&2
        exit 1
      fi
      sleep "$poll"
      waited=$((waited + poll))
    done
    echo "APP_ROLE=admin: database schema is ready (at the migration head)"
    ;;
  *)
    echo "entrypoint: unknown APP_ROLE '$role' (expected bot, admin or all)" >&2
    exit 1
    ;;
esac

exec uv run --no-sync python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
