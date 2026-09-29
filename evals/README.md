# Promptfoo evals

Audits the WhatsApp agent through `POST /internal/eval/chat`:

```
promptfoo -> FastAPI -> LangGraph -> fake Dentalink / fake YCloud (in memory)
```

No real patient data or WhatsApp traffic is involved. **Never point this at
production** (`agent.qeva-ai.com`).

## What the endpoint really runs

- Everything behind the endpoint is a fake: Dentalink (no patients, no
  professionals, no slots seeded), YCloud, Telegram, Linear and the **LLM**
  (`FakeLLMProvider`). `LLM_API_URL`/`LLM_API_KEY` are ignored here.
- LLM-worded replies therefore come back as `[fake-response for intent=...]`.
  Static, code-built parts are real: reply kind, buttons, list rows, the intake
  bullet lists, the handoff message, node and tool names.
- Datasets tag their tests with `metadata.requires_real_llm`. The `true` ones
  assert wording and fail on purpose against the placeholder (see
  `assertions/custom.js`); run only the deterministic ones with
  `--filter-metadata requires_real_llm=false`.
- The 6 older datasets use `llm-rubric` and grade whatever the fake stack replies.
  Their result is only meaningful once the endpoint can use a real LLM.
- State lives in the server process, keyed by `conversation_id` (LRU of 256
  conversations), so multi-turn scenarios work; restart the server to reset it.

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

`datasets/flows_view_appointment.yaml` is not enabled in the config: it needs a
patient with appointments seeded in the eval stack, which does not exist yet.
