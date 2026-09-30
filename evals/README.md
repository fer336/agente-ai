# Promptfoo evals

Audits the WhatsApp agent through `POST /internal/eval/chat`:

```
promptfoo -> FastAPI -> LangGraph -> fake Dentalink / fake YCloud (in memory)
```

No real patient data or WhatsApp traffic is involved. **Default stance: do not point
this at production** (`agent.qeva-ai.com`); run it locally. Production is an explicit,
temporary, documented exception, see "Run against production" at the end.

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

2. The app, from the repository root. Use a fresh shell and do **not** load
   any production env file (its `REDIS_HOST` would point the lock at production);
   the only variables the local run needs are the non-secret ones below:

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
`memory:contact:eval-contact-<eval conversation id>:summary` and the shared read cache `runtime_agent_config`,
and the application logs. Repositories, Dentalink, YCloud, Chatwoot, Telegram,
Linear/incidents, traces and the checkpointer are per-conversation in-memory fakes.
The admin login you need for the cookies writes one entry to `admin_audit_log`.

**Exposure while enabled.** Any authenticated admin session (every role) can call
`POST /internal/eval/chat`, and with `INTERNAL_EVAL_REAL_LLM=true` each call spends
real LLM budget. Keep both flags on only for the audit window and remove them right
after (step 6).

**Single process.** The eval conversation state lives in the memory of one process.
The backend runs one uvicorn process (`entrypoint.sh` has no `--workers`) and the
stack has `replicas: 1`; keep it that way during the audit. If the service was ever
scaled, run `docker service scale agente-clinica_backend=1` first, otherwise turns of
one conversation land on different processes and the scenarios break.

1. **Variables to add** (names only, both non-secret): `INTERNAL_EVAL_ENABLED=true`
   and `INTERNAL_EVAL_REAL_LLM=true`. `LLM_API_URL`, the LLM key, `LLM_MODEL` and
   `ADMIN_SESSION_SECRET` must already be configured in the existing secret. Do
   **not** copy or re-create the production secret file: service environment variables
   take precedence over the secret's env file, so the two flags are added directly to
   the service and the existing secret stays untouched. Optionally add
   `ADMIN_SESSION_TTL_SECONDS` (default 3600 s) if the run lasts longer than an hour.

   ```bash
   docker service update \
     --env-add INTERNAL_EVAL_ENABLED=true \
     --env-add INTERNAL_EVAL_REAL_LLM=true \
     agente-clinica_backend
   ```

   (This restarts the task once. A later `docker stack deploy` or release redeploy
   drops these variables, so do not release during the audit.)
2. **Admin cookies** from the production admin login (any role; the account must
   already exist; the login adds one `admin_audit_log` entry). The password is read
   from a silent prompt and sent on stdin, so it never appears in argv or shell
   history. The cookies are `Secure`, so use https:

   ```bash
   read -r -p 'Admin user: ' ADMIN_USER
   read -r -s -p 'Admin password: ' ADMIN_PASSWORD; echo
   jq -n --arg u "$ADMIN_USER" --arg p "$ADMIN_PASSWORD" '{username:$u,password:$p}' \
     | curl -sS -c /tmp/eval-cookies.txt -H 'Content-Type: application/json' \
         --data @- https://agent.qeva-ai.com/admin/login      # -> {"role":"..."}
   unset ADMIN_PASSWORD
   export ADMIN_SESSION_COOKIE="$(awk '$6=="admin_session"{print $7}' /tmp/eval-cookies.txt)"
   export ADMIN_CSRF_COOKIE="$(awk '$6=="admin_csrf"{print $7}' /tmp/eval-cookies.txt)"
   rm /tmp/eval-cookies.txt
   ```

   (curl prefixes the `HttpOnly` cookie's domain with `#HttpOnly_`, but the cookie
   name stays in column 6, so the `awk` above still finds it.)
3. **Grader for `llm-rubric`**: promptfoo's default grader is OpenAI
   (`OPENAI_API_KEY`). To use an OpenAI-compatible gateway such as OpenRouter, set in
   `defaultTest` of `promptfooconfig.yaml`:

   ```yaml
   defaultTest:
     options:
       provider:
         id: openai:chat:<GRADER_MODEL>          # e.g. a Gemini model id on OpenRouter
         config:
           apiBaseUrl: https://openrouter.ai/api/v1
           apiKeyEnvar: EVAL_GRADER_API_KEY
   ```

   and `export EVAL_GRADER_API_KEY=<key>`. This follows promptfoo's OpenAI-provider
   options and was not executed here. A self-hosted 9Router
   (`host.docker.internal:20128`) is not reachable from your workstation.
4. **Run** (from the repository root):

   ```bash
   export INTERNAL_EVAL_BASE_URL=https://agent.qeva-ai.com
   export EVAL_RUN_ID="$(date +%s)"
   npx promptfoo@latest eval -c evals/promptfooconfig.yaml --no-cache
   ```

   Each conversation id is suffixed with `EVAL_RUN_ID`, so runs never reuse server
   state. Every turn costs one or more real LLM calls.
5. **Verify** the endpoint answers before the full run: a single tap-free turn with
   `curl` using the two cookies and the `X-CSRF-Token` header should return 200, not 404.
6. **Rollback** (right after the run): remove the two variables. The original secret
   was never modified, so nothing else needs restoring.

   ```bash
   docker service update \
     --env-rm INTERNAL_EVAL_ENABLED \
     --env-rm INTERNAL_EVAL_REAL_LLM \
     agente-clinica_backend
   ```

   With `INTERNAL_EVAL_ENABLED` unset the endpoint answers 404 again.
