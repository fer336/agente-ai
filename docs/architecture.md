# Fundación técnica del Agente de IA — arquitectura implementada

Esta es la base ejecutable del Agente de IA para la clínica dental: un monolito modular con arquitectura hexagonal (Python + FastAPI + LangGraph + PostgreSQL + Redis), con los 4 adaptadores externos (Dentalink, WhatsApp, Chatwoot, LLM) todavía simulados. Sirve para validar que el esqueleto completo funciona de punta a punta antes de conectar integraciones reales. El diseño completo de producto vive en [`arquitectura-agente-ia-clinica-dental.md`](../arquitectura-agente-ia-clinica-dental.md); este documento cubre lo que ya está construido.

## Quick path

1. `cp .env.example .env` y completá tus datos reales de Postgres/Redis (host, puerto, usuario, password, db).
2. `docker-compose up -d postgres redis` (o apuntá `.env` a tu propio servidor).
3. `pip install -e ".[dev]"`
4. `python -m alembic upgrade head`
5. `pytest` → esperado: 89/89 passed, 0 skipped.
6. `python -m app.main` (o `uvicorn app.main:app`) → `GET /health` y `GET /ready` deberían responder 200.

## Details

| Tema | Decisión |
|------|----------|
| Carpetas | Árbol hexagonal de la sección 22 del doc de arquitectura (`domain/application/infrastructure/api/agent/config`), no la plantilla genérica en capas de `fastapi-templates`. |
| Dominio | Solo Protocols (`AppointmentGateway`, `MessagingGateway`, `HumanHandoffGateway`, `LLMProvider`) y entidades shell. El dominio no importa FastAPI, SQLAlchemy, Redis ni LangGraph. |
| Grafo LangGraph | Un nodo real, `search_availability`, wireado tool → caso de uso → gateway, contra `FakeDentalinkGateway`. |
| Checkpointer | `AsyncPostgresSaver` con su propio pool `psycopg` (autocommit=True — `setup()` corre `CREATE INDEX CONCURRENTLY`, que Postgres no permite dentro de una transacción). Pool separado del engine `asyncpg` de SQLAlchemy. |
| Configuración | `Settings` con campos discretos (`APP_HOST/PORT`, `POSTGRES_*`, `REDIS_*` incluyendo `REDIS_PASSWORD`) pensados para correr en tu propio servidor, no solo docker-compose local. |
| Adaptadores | 4 fakes en memoria (`FakeDentalinkGateway`, `FakeWhatsAppGateway`, `FakeChatwootGateway`, `FakeLLMProvider`) detrás de los Protocols de dominio — swap point para las integraciones reales. |
| Migraciones | Alembic async, revisión base vacía (`0001_base`) — solo prueba el pipeline, sin schema de negocio todavía. |
| Fuera de alcance | Integraciones reales, flujos de negocio completos (pending actions/outbox/idempotencia), n8n, workers/scheduler, infraestructura de deploy más allá de docker-compose, contenido clínico. |

## Checklist

- [x] `docker-compose up` levanta Postgres y Redis.
- [x] `alembic upgrade head` corre limpio contra Postgres real.
- [x] `/health` y `/ready` responden 200.
- [x] El grafo LangGraph ejecuta un ciclo completo con el checkpointer Postgres persistiendo y restaurando estado por `thread_id`.
- [x] Los 4 adaptadores fake cumplen sus Protocols de dominio.
- [x] Suite completa (89/89) verde contra infraestructura real, sin skips.
- [x] `ruff` y `mypy --strict` limpios.

## Next step

Etapa 1 del plan de implementación (`arquitectura-agente-ia-clinica-dental.md`, sección 27): dominio completo (entidades reales, value objects adicionales, eventos), seguido de persistencia real de acciones pendientes, outbox e idempotencia — recién después se conectan WhatsApp, Chatwoot y Dentalink reales.
