# Clinic AI Agent

AI agent foundation for a dental clinic appointment assistant. Hexagonal
architecture: `app/domain`, `app/application`, `app/infrastructure`,
`app/api`, `app/agent`, `app/config`.

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

## Run tests

```bash
pytest
```

Run only the domain unit tests:

```bash
pytest tests/unit/domain
```
