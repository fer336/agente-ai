# Fundación técnica del Agente de IA — arquitectura implementada

Esta es la base ejecutable del Agente de IA para la clínica dental: un monolito modular con arquitectura hexagonal (Python + FastAPI + LangGraph + PostgreSQL + Redis). El diseño completo de producto, alcance del MVP y reglas de negocio viven en [`PRD.md`](../PRD.md) — este documento cubre únicamente lo que ya está construido en el código.

## Quick path

1. `cp dotenv_example_template.txt .env` y completá tus datos reales de Postgres/Redis/YCloud (host, puerto, usuario, password, db; API key y número de WhatsApp de YCloud si vas a probar contra integraciones reales).
2. `docker-compose up -d postgres redis` (o apuntá `.env` a tu propio servidor).
3. `pip install -e ".[dev]"`
4. `python -m alembic upgrade head`
5. `pytest` → esperado: suite verde salvo el test de checkpointer Postgres si no tenés un Postgres real corriendo localmente (`tests/agent/test_checkpointer_postgres.py`, requiere conexión real).
6. `python -m app.main` (o `uvicorn app.main:app`) → `GET /health` y `GET /ready` deberían responder 200.

## Details

| Tema | Decisión |
|------|----------|
| Carpetas | Árbol hexagonal: `domain/application/infrastructure/api/agent/config`, no la plantilla genérica en capas de `fastapi-templates`. |
| Dominio | Solo Protocols (`AppointmentGateway`, `MessagingGateway`, `HumanHandoffGateway`, `LLMProvider`, `AgentInvoker`) y entidades/value objects. El dominio no importa FastAPI, SQLAlchemy, Redis ni LangGraph. |
| Mensajería | YCloud es el único canal de WhatsApp (PRD §24) — reemplaza cualquier integración previa. `MessagingGateway` cubre envío de texto y botones interactivos; `HumanHandoffGateway` cubre la derivación a administración vía el Shared Team Inbox de YCloud. Ambos adaptadores reales (`YCloudMessagingGateway`, `YCloudHandoffGateway`, `httpx`-based) existen en `app/infrastructure/ycloud/` pero todavía no están wireados en DI — no hay credenciales reales de YCloud en este entorno. |
| Grafo LangGraph | Un nodo real, `search_availability`, wireado tool → caso de uso → gateway, contra `FakeDentalinkGateway`. El resto del grafo de PRD §29 (`appointment`/`agreement`/`handoff`/`fallback`/`handle_error`) todavía no existe. |
| Checkpointer | `AsyncPostgresSaver` con su propio pool `psycopg` (autocommit=True — `setup()` corre `CREATE INDEX CONCURRENTLY`, que Postgres no permite dentro de una transacción). Pool separado del engine `asyncpg` de SQLAlchemy. |
| Configuración | `Settings` con campos discretos (`APP_HOST/PORT`, `POSTGRES_*`, `REDIS_*`, `YCLOUD_*`) pensados para correr en tu propio servidor, no solo docker-compose local. |
| Adaptadores | Fakes en memoria detrás de los Protocols de dominio (swap point para las integraciones reales): `FakeDentalinkGateway`, `FakeYCloudMessagingGateway`, `FakeYCloudHandoffGateway`, `FakeLLMProvider`, `FakeAgentInvoker`/`NotImplementedAgentInvoker`. |
| Pipeline de mensajes entrantes | Webhook YCloud → dedupe por `external_message_id` → resolver/crear contacto y conversación (por número de teléfono) → persistir mensaje → gate de modo `HUMAN` → debounce → lock por conversación → seam hacia el agente (`IngestMessageUseCase`, PRD §4/§37). |
| Migraciones | Alembic async: `0001_base` (pipeline vacío) + `0002_core_schema` (patients, contacts, conversations, messages, appointments, appointment_actions, pending_actions, tool_executions, human_handoffs, approved_contents, outbox_events). |
| Fuera de alcance (todavía) | Flujos completos de turnos/obras sociales (crear/reprogramar/cancelar, `ScheduledAction`, vencimiento de propuestas), audio/transcripción, observabilidad completa (`agent_runs`/`node_executions`/`errors`/`incidents`), Telegram, Linear, Promptfoo, panel `/admin`, workers/scheduler, integración real de Dentalink y YCloud. Ver PRD §70 para el orden de implementación completo. |

## Checklist

- [x] `docker-compose up` levanta Postgres y Redis.
- [x] `alembic upgrade head` corre limpio contra Postgres real.
- [x] `/health` y `/ready` responden 200.
- [x] El grafo LangGraph ejecuta un ciclo completo con el checkpointer Postgres persistiendo y restaurando estado por `thread_id`.
- [x] Los adaptadores fake cumplen sus Protocols de dominio.
- [x] Suite unitaria completa verde; los tests de integración con Postgres/Redis reales requieren esos servicios corriendo (se saltean si no están disponibles, salvo el test del checkpointer que sí los necesita).
- [x] `ruff` y `mypy --strict` limpios.

## Next step

Seguir el orden de implementación del PRD (`PRD.md`, sección 70): completar el dominio de turnos y obras sociales, conectar el gateway real de Dentalink, wirear los adaptadores reales de YCloud, y construir el resto del grafo LangGraph antes de sumar observabilidad (Telegram/Linear/Promptfoo) y el panel `/admin`.
