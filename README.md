# Clinic AI Agent

AI agent foundation for a dental clinic appointment assistant. Hexagonal
architecture: `app/domain`, `app/application`, `app/infrastructure`,
`app/api`, `app/agent`, `app/config`.

## Architecture

```mermaid
flowchart TB
    WhatsApp["WhatsApp"] --> YCloud["YCloud"]
    YCloud -->|webhook| Webhook

    subgraph API["app/api"]
        Webhook["POST /webhooks/ycloud/{secret}"]
        Health["/health, /ready"]
    end

    subgraph Agent["app/agent — LangGraph"]
        SearchNode["search_availability node"]
    end

    subgraph Application["app/application — use cases"]
        Ingest["IngestMessageUseCase"]
        SendReply["SendReplyUseCase"]
        SearchAvail["SearchAvailabilityUseCase"]
    end

    subgraph Domain["app/domain — Protocols, zero deps"]
        ApptGW[["AppointmentGateway"]]
        MsgGW[["MessagingGateway"]]
        HandoffGW[["HumanHandoffGateway"]]
        LLMP[["LLMProvider"]]
        AgentInv[["AgentInvoker"]]
    end

    subgraph Infra["app/infrastructure — adapters"]
        Dentalink["FakeDentalinkGateway"]
        YCloudMsg["FakeYCloudMessagingGateway<br/>(real YCloudMessagingGateway not wired)"]
        YCloudHandoff["FakeYCloudHandoffGateway<br/>(real YCloudHandoffGateway not wired)"]
        LLMFake["FakeLLMProvider"]
        AgentStub["NotImplementedAgentInvoker<br/>(Etapa 5 seam, not yet wired to LangGraph)"]
        PG[("PostgreSQL")]
        Redis[("Redis")]
    end

    Webhook --> Ingest
    Ingest --> AgentInv
    Ingest --> PG
    Ingest --> Redis
    SearchNode --> SearchAvail
    SearchAvail --> ApptGW
    SendReply --> MsgGW

    ApptGW --> Dentalink
    MsgGW --> YCloudMsg
    HandoffGW --> YCloudHandoff
    LLMP --> LLMFake
    AgentInv --> AgentStub
```

Layered hexagonal design: `API → Agent (LangGraph) → Application (use cases)
→ Domain (Protocols, zero deps) → Infrastructure (adapters)`, with PostgreSQL
as the LangGraph checkpointer and Redis reserved for debounce/locks/rate-limit.
YCloud is the sole WhatsApp channel (replaces any prior messaging setup —
see [`PRD.md`](PRD.md) §24). All infrastructure adapters (Dentalink, YCloud
messaging, YCloud handoff, LLM) are in-memory fakes today — deliberate swap
points for the real integrations; the real `httpx`-based YCloud adapters
already exist in `app/infrastructure/ycloud/` but aren't wired into DI yet
(no live YCloud credentials in this environment). See
[`docs/architecture.md`](docs/architecture.md) for the full breakdown of
what's implemented, what's out of scope, and the next steps, and
[`PRD.md`](PRD.md) for the full product scope and business rules.

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
cp dotenv_example_template.txt .env
```

`dotenv_example_template.txt` documents discrete settings — `APP_HOST`/`APP_PORT`
(the FastAPI bind address, since the app can run on your own server, not only
via docker-compose), `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_USER`/
`POSTGRES_PASSWORD`/`POSTGRES_DB`, `REDIS_HOST`/`REDIS_PORT`, and
`YCLOUD_API_URL`/`YCLOUD_API_KEY`/`YCLOUD_WEBHOOK_SECRET`/`YCLOUD_WHATSAPP_NUMBER`.
`DATABASE_URL` and `REDIS_URL` are derived automatically from those fields by
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
