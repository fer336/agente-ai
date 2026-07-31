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

Edit `.env` if you need non-default `DATABASE_URL` / `REDIS_URL` values.

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
