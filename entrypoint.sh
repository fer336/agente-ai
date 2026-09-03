#!/bin/sh
set -eu

uv run --no-sync python -m alembic upgrade head

exec uv run --no-sync python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
