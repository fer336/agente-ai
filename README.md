# Clinic AI Agent

AI agent foundation for a dental clinic appointment assistant. Hexagonal
architecture: `app/domain`, `app/application`, `app/infrastructure`,
`app/api`, `app/agent`, `app/config`.

## Architecture

![Hexagonal architecture overview](animated-svg-hexagonal-foundation/renders/hexagonal-foundation.gif)

Layered hexagonal design: `API → Agent (LangGraph) → Application (use cases)
→ Domain (Protocols, zero deps) → Infrastructure (adapters)`, with PostgreSQL
as the LangGraph checkpointer and Redis reserved for debounce/locks/rate-limit.
All four infrastructure adapters (Dentalink, WhatsApp, Chatwoot, LLM) are
in-memory fakes today — deliberate swap points for the real integrations.
See [`docs/architecture.md`](docs/architecture.md) for the full breakdown of
what's implemented, what's out of scope, and the next steps.

## Requirements

- Python 3.11+
- Docker + Docker Compose (for Postgres/Redis)

## Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Configure environment

```bash
cp .env.example .env
```

`.env.example` documents discrete settings — `APP_HOST`/`APP_PORT` (the FastAPI
bind address, since the app can run on your own server, not only via
docker-compose), `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_USER`/
`POSTGRES_PASSWORD`/`POSTGRES_DB`, and `REDIS_HOST`/`REDIS_PORT`. `DATABASE_URL`
and `REDIS_URL` are derived automatically from those fields by
`app.config.settings` — you don't need to set them directly. Edit `.env` if
your Postgres/Redis run somewhere other than `localhost`.

## Start local services

```bash
docker compose up -d postgres redis
```

## Run database migrations

```bash
alembic upgrade head
```

## Run the app

```bash
uvicorn app.main:app --reload
```

Or, using the values from `APP_HOST`/`APP_PORT` in your `.env`:

```bash
python -m app.main
```

Once running, `GET /health` reports liveness (no dependency checks) and
`GET /ready` reports readiness (checks Postgres and Redis connectivity).

## Run tests

```bash
pytest
```

Run only the domain unit tests:

```bash
pytest tests/unit/domain
```
