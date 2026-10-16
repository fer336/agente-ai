# Split the admin panel into its own service

Branch: `feat/split-admin-service` (from `origin/main`). Status: in progress, started 2026-10-16.

## Objective
Run the admin panel (`/admin/*`) as a separate Swarm service from the bot (WhatsApp and Chatwoot webhooks, workers, migrations), built from the same image, so a panel crash or heavy query cannot affect message handling.

## Problem
Today one FastAPI app and one Swarm service (`backend`, 1 replica, host `agent.qeva-ai.com`) serve both. `app/main.py` mounts every router and starts the follow-up and reminder workers in its lifespan; `entrypoint.sh` runs migrations.

## Decisions made with the user
- Same host: the panel stays at `agent.qeva-ai.com/admin`, Traefik routes `Host(...) && PathPrefix(/admin)` to the new service with an explicit higher priority. No new DNS, certificate or cookie change.
- Same image, role chosen by `APP_ROLE=bot|admin|all`. Default `all` keeps today's behavior for anyone who does not set it.

## Mapping evidence (explorer, 2026-10-16)
- Bot only: webhook and chatwoot webhook routers, `/public` static mount (WhatsApp fetches it by URL), `/internal/eval` (outside `/admin`), follow-up and reminder workers, migrations (`entrypoint.sh`).
- Admin only: auth, `/admin/api` routers, docs router, pages router, `/admin/static` mount.
- Shared: `/health` and `/ready` (not under `/admin`, so the admin service needs its own Swarm healthcheck, not Traefik), logging, lazy Redis/DB/checkpointer clients; `close_agent_checkpointer()` is a no-op if never opened.
- The panel needs YCloud settings for `/admin/api/flows/*` and `ycloud_configured`, so it keeps those secrets.
- Redis holds the LLM-config cache and the debounce key, Postgres is the source of truth: no in-process bot state found that the panel depends on. Open check: an admin conversation reset while the bot has a debounce task already sleeping in memory.
- `pin-compose` in `.github/workflows/release.yml` rewrites every `image:` line with the prefix, so both services get pinned together; `verify-health` polls `/ready` on the bot host.

## Scope
- `app_role` setting and a `create_app(role)` factory in `app/main.py`; `app = create_app(...)` stays at module level.
- Role-aware `entrypoint.sh` (migrations only for `bot` and `all`).
- `docker-stack.yml`: `backend` gets `APP_ROLE=bot`, new `admin` service with Traefik rule, priority, port and healthcheck; `docker-compose.yml` and docs updated.

## Out of scope
- Separate repository or image; subdomain; changing admin features.

## Constraints
- English artifacts; test first; default `all` must not change behavior; push, PR, merge and the production deploy are the user's decisions.

## Tasks
- [x] S1 `APP_ROLE` setting and `create_app(role)` factory with per-role router, mount and lifespan selection + tests (admin app 404s webhook paths, bot app 404s `/admin`, `all` unchanged).
- [x] S2 Role-aware `entrypoint.sh` and compose update.
- [x] S3 `docker-stack.yml` admin service, Traefik priority, healthchecks, docs/runbook.
- [x] S4 Resolve the open reset/debounce check and record the result. Evidence: `DebounceTracker.clear` only deletes the Redis key (`app/infrastructure/redis/debounce.py:48`) and `is_stale` treats a missing key as NOT stale (`:42`), so a reset never cancelled a bot task already sleeping in memory, in one process or two. Splitting does not change that behavior. Pre-existing and out of scope: a reset during an in-flight debounce window can still let the pending turn run.
- [x] S5 From the native review (reliability warning, `entrypoint.sh`): the admin role skips migrations and nothing orders it after the bot, so after a release with a migration it can serve on the old schema. The admin entrypoint must wait until `alembic current` reports head (bounded wait, then exit non-zero so Swarm restarts it) + test with a fake `uv`.

S1 evidence: unit 3681 passed (3 known failures), ruff/mypy clean, RED observed (ImportError). Not verified: real uvicorn with APP_ROLE=admin|bot.

S2+S3 evidence: unit 3688 passed (3 known failures), ruff/mypy clean; entrypoint checked with a fake `uv` for admin/bot/all/unset/unknown; stack validated offline with `docker compose config -q` and `docker stack config`; 7 stack tests with RED observed; release pin step passes with two `image:` lines (grep needs at least one match). Admin healthcheck uses /health (not /ready) on purpose to avoid restart loops on a Postgres/Redis blip. Not verified: a real Swarm/Traefik run, `python` on PATH in the image (copied from compose), uvicorn with APP_ROLE=admin|bot.

S5 evidence: unit 3696 passed (3 known failures), ruff/mypy clean, RED observed (3 failed before), 8 entrypoint tests with a fake `uv`; alembic prints `<rev> (head)` at head (checked in alembic 1.19.0 source). Not verified: live DB, real Swarm retry, dash as /bin/sh in the image; multiple heads would pass on any `(head)` (repo has a single head).

Native review (4 lenses, high risk, 2026-10-16): approved, no blocking findings. Warning R3 became S5. Readability suggestions left for later: one source for the valid role names (`app/main.py`, `Settings`, `entrypoint.sh`), and group the per-role router registration in `create_app`.

## Acceptance criteria
- With `APP_ROLE` unset, the app behaves exactly as today.
- `bot` serves webhooks, `/public`, `/internal/eval`, health and runs the workers; `admin` serves `/admin/*` and health and starts no workers.
- Unit suite green except the 3 known failures in `tests/unit/api/dependencies/test_gateway_dependency.py`.

## Next step
All tasks done. Open decisions are the user's: push, PR, merge, release, deploy. Optional follow-up: one source for the valid role names.
