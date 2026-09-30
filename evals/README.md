# Promptfoo evals

Audits the WhatsApp agent through `POST /internal/eval/chat`:

```
promptfoo -> FastAPI -> LangGraph -> fake Dentalink / fake YCloud (in memory)
```

No real patient data or WhatsApp traffic is involved. **Never point this at
production** (`agent.qeva-ai.com`).

## What the endpoint really runs

- Behind the endpoint everything is an isolated in-memory fake: Dentalink (one
  seeded patient, 2 professionals, free slots), YCloud, Telegram, Linear, every
  repository, the incident/error path and the LangGraph checkpointer.
- The **LLM** is `FakeLLMProvider` by default (replies come back as
  `[fake-response for intent=...]`). With `INTERNAL_EVAL_REAL_LLM=true` it is the
  same provider the webhook path uses (`LLM_API_URL`, honoring the admin runtime
  LLM config); if `LLM_API_URL` is empty the endpoint answers 503 instead of
  silently faking.
- Seeded patient: **Lucía Prueba, DNI 39000111**, two upcoming appointments
  (Dra. Ana Ejemplo / Ortodoncia, Dr. Bruno Muestra / Odontología general) and free
  slots `eval-free-1..3` (`app/infrastructure/dentalink/eval_seed.py`).
- Datasets tag tests with `metadata.requires_real_llm`. The `true` ones grade
  LLM wording and fail on purpose against the fake placeholder; with the fake LLM
  run only `--filter-metadata requires_real_llm=false`.
- State lives in the server process, keyed by `conversation_id` (LRU of 256
  conversations), so multi-turn scenarios work; restart to reset it.
- Not reproducible through this endpoint (noted in `appointments.yaml`): a slot
  taken by someone else between pick and confirm, and an expired confirmation.

## Local run

Needs only **Redis** (the agent's per-conversation lock) and the app process.
No Postgres and no migrations: the eval stack uses in-memory repositories and a
`MemorySaver`, and the admin session cookie is a stateless signed token.

Use ports that cannot collide with the production Swarm stack (it publishes
none itself, but the shared Postgres/Redis services on this host may use
`5432`/`6379`, and `docker-compose.yml` would bind `8000`/`5432`/`6379`). Do
**not** use `docker-compose.yml` for this run.

1. A throwaway Redis on a private port (bound to loopback only):

   ```bash
   docker run --rm -d --name eval-redis -p 127.0.0.1:16379:6379 redis:7-alpine
   ```

2. The app, from the repository root. Use a fresh shell and do **not** copy
   the production `.env` (its `REDIS_HOST` would point the lock at production):

   ```bash
   export ADMIN_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
   export INTERNAL_EVAL_ENABLED=true
   export ADMIN_SESSION_TTL_SECONDS=14400
   export REDIS_HOST=127.0.0.1 REDIS_PORT=16379
   uv run uvicorn app.main:app --host 127.0.0.1 --port 18000
   ```

3. In another shell with the same `ADMIN_SESSION_SECRET`, mint the two cookies
   (no login and no database needed):

   ```bash
   eval "$(uv run python - <<'PY'
   import os
   from datetime import UTC, datetime
   from app.config.settings import Settings
   from app.infrastructure.auth.session_tokens import create_session_token

   s = Settings(_env_file=None)
   session, csrf = create_session_token(
       "eval-runner", "eval-runner", "ADMIN_TECHNICAL",
       s.admin_session_secret, s.admin_session_ttl_seconds, now=datetime.now(UTC),
   )
   print(f"export ADMIN_SESSION_COOKIE={session}")
   print(f"export ADMIN_CSRF_COOKIE={csrf}")
   PY
   )"
   ```

4. Run promptfoo (Node 20+):

   ```bash
   export INTERNAL_EVAL_BASE_URL=http://127.0.0.1:18000
   export EVAL_RUN_ID="$(date +%s)"   # unique per run: keeps conversation ids fresh
   npx promptfoo@latest eval -c evals/promptfooconfig.yaml --no-cache \
     --filter-metadata requires_real_llm=false
   ```

5. Clean up: `docker stop eval-redis` and stop uvicorn.

### Environment variables you provide

| Variable | Used by | Notes |
| --- | --- | --- |
| `ADMIN_SESSION_SECRET` | app + cookie script | random, local only |
| `INTERNAL_EVAL_ENABLED` | app | `true` |
| `REDIS_HOST`, `REDIS_PORT` | app | the throwaway Redis |
| `ADMIN_SESSION_TTL_SECONDS` | app | optional, default 3600 |
| `INTERNAL_EVAL_BASE_URL` | promptfoo | `http://127.0.0.1:18000` |
| `ADMIN_SESSION_COOKIE`, `ADMIN_CSRF_COOKIE` | promptfoo | from step 3 |
| `EVAL_RUN_ID` | promptfoo | unique per run |
| `OPENAI_API_KEY` | promptfoo (`llm-rubric` grader) | the default grader is OpenAI; or set `defaultTest.options.provider` to another grader |

## Multi-turn scenarios

A conversation is a run of consecutive tests sharing `conversation_id`, with
descriptions ending in `— turn N`. `evaluateOptions.maxConcurrency: 1` makes
promptfoo run them in order and `cache: false` stops it from replaying stored
replies. The provider appends `EVAL_RUN_ID` to every conversation id. A test
that taps a button sets `button_payload` (the id) and `message` (the title).

Response shape: `reply_text`, `reply_kind` (`text|buttons|list|flow|null`),
`buttons[{id,title}]`, `list_rows[{id,title,description}]`, `flow`,
`node_names`, `tool_names`, `agent_run_id`, `agent_run_status`.

`datasets/flows_view_appointment.yaml` uses the seeded eval patient (Lucía Prueba,
DNI 39000111, two upcoming appointments; `app/infrastructure/dentalink/eval_seed.py`).

## Run against production

Explicit decision: the audit runs against `https://agent.qeva-ai.com` (PRD §74.3
allows the endpoint "salvo necesidad expresa", behind admin auth). Enable it only for
the duration of the run and roll back afterwards.

**What the eval turns share with production** (real LLM on): the LLM endpoint
(cost and its logs), one read of the admin runtime LLM config from Postgres (no
writes), the Redis keys `lock:conversation:<eval id>`, `lock:appointment:eval-prof-*:<start>`,
`memory:contact:eval-contact:summary` and the shared read cache `runtime_agent_config`,
and the application logs. Repositories, Dentalink, YCloud, Chatwoot, Telegram,
Linear/incidents, traces and the checkpointer are per-conversation in-memory fakes.
The admin login you need for the cookies writes one entry to `admin_audit_log`.

1. **Secret variables to add** to the backend env (names only):
   `INTERNAL_EVAL_ENABLED=true` and `INTERNAL_EVAL_REAL_LLM=true`. `LLM_API_URL`,
   `LLM_API_KEY`/`OPENROUTER_API_KEY`, `LLM_MODEL` and `ADMIN_SESSION_SECRET` must
   already be there. Optionally raise `ADMIN_SESSION_TTL_SECONDS` (default 3600 s)
   if the run is longer than an hour.
2. **Swarm secrets are immutable**, so create a new one from your local copy of the
   env file (Swarm never shows a secret's contents), then swap it on the service
   (service name from the stack: `agente-clinica_backend`; alternatively rename it in
   `docker-stack.yml` as its header comment describes and redeploy):

   ```bash
   cp <your-backend.env> eval.env
   printf '\nINTERNAL_EVAL_ENABLED=true\nINTERNAL_EVAL_REAL_LLM=true\n' >> eval.env
   docker secret create agente_ai_backend_env_eval eval.env
   docker service update \
     --secret-rm agente_ai_backend_env \
     --secret-add source=agente_ai_backend_env_eval,target=/run/secrets/backend.env \
     agente-clinica_backend
   ```

   Do not cut a release during the audit: the release pipeline redeploys the stack
   file and would restore the old secret mid-run.
3. **Admin cookies** from the production admin login (any role works; the account
   must already exist). The cookies are `Secure`, so use https:

   ```bash
   curl -sS -c /tmp/eval-cookies.txt -H 'Content-Type: application/json' \
     -d '{"username":"<ADMIN_USER>","password":"<ADMIN_PASSWORD>"}' \
     https://agent.qeva-ai.com/admin/login          # -> {"role":"..."}
   export ADMIN_SESSION_COOKIE="$(awk '$6=="admin_session"{print $7}' /tmp/eval-cookies.txt)"
   export ADMIN_CSRF_COOKIE="$(awk '$6=="admin_csrf"{print $7}' /tmp/eval-cookies.txt)"
   rm /tmp/eval-cookies.txt
   ```

   (curl prefixes the `HttpOnly` cookie's domain with `#HttpOnly_`, but the cookie
   name stays in column 6, so the `awk` above still finds it.)
4. **Grader for `llm-rubric`**: promptfoo's default grader is OpenAI
   (`OPENAI_API_KEY`). To use the same OpenAI-compatible gateway the agent uses
   (OpenRouter), set in `defaultTest` of `promptfooconfig.yaml`:

   ```yaml
   defaultTest:
     options:
       provider:
         id: openai:chat:<GRADER_MODEL>          # e.g. a Gemini model id on OpenRouter
         config:
           apiBaseUrl: https://openrouter.ai/api/v1
           apiKeyEnvar: EVAL_GRADER_API_KEY
   ```

   and `export EVAL_GRADER_API_KEY=<key>`. This config shape follows promptfoo's
   OpenAI-provider options and was not executed here. A self-hosted 9Router
   (`host.docker.internal:20128`) is not reachable from your workstation.
5. **Run** (from the repository root):

   ```bash
   export INTERNAL_EVAL_BASE_URL=https://agent.qeva-ai.com
   export EVAL_RUN_ID="$(date +%s)"
   npx promptfoo@latest eval -c evals/promptfooconfig.yaml --no-cache
   ```

   Each conversation id is suffixed with `EVAL_RUN_ID`, so runs never reuse server
   state. Every turn costs one or more real LLM calls.
6. **Rollback**: swap back and remove the eval secret.

   ```bash
   docker service update \
     --secret-rm agente_ai_backend_env_eval \
     --secret-add source=agente_ai_backend_env,target=/run/secrets/backend.env \
     agente-clinica_backend
   docker secret rm agente_ai_backend_env_eval && shred -u eval.env
   ```

   The original secret is untouched, so this restores the previous configuration
   (`INTERNAL_EVAL_ENABLED` unset means the endpoint answers 404 again).
