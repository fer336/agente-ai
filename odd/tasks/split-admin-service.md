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
- [ ] S1 `APP_ROLE` setting and `create_app(role)` factory with per-role router, mount and lifespan selection + tests (admin app 404s webhook paths, bot app 404s `/admin`, `all` unchanged).
- [ ] S2 Role-aware `entrypoint.sh` and compose update.
- [ ] S3 `docker-stack.yml` admin service, Traefik priority, healthchecks, docs/runbook.
- [ ] S4 Resolve the open reset/debounce check and record the result.

## Acceptance criteria
- With `APP_ROLE` unset, the app behaves exactly as today.
- `bot` serves webhooks, `/public`, `/internal/eval`, health and runs the workers; `admin` serves `/admin/*` and health and starts no workers.
- Unit suite green except the 3 known failures in `tests/unit/api/dependencies/test_gateway_dependency.py`.

## Next step
S1.
