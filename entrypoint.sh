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
    ;;
  *)
    echo "entrypoint: unknown APP_ROLE '$role' (expected bot, admin or all)" >&2
    exit 1
    ;;
esac

exec uv run --no-sync python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
