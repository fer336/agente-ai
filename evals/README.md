# Promptfoo evals

Audits the WhatsApp agent through `POST /internal/eval/chat`:

```
promptfoo -> FastAPI -> LangGraph -> fake Dentalink / fake YCloud (in memory)
```

No real patient data or WhatsApp traffic is involved. **Default stance: iterate locally**;
production audits are an always-on posture run with `evals/run-audit.sh`, see "Production
audits" at the end.

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
   npx promptfoo@0.123.1 eval -c evals/promptfooconfig.yaml --no-cache \
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
| `EVAL_GRADER_API_KEY`, `EVAL_GRADER_BASE_URL`, `EVAL_GRADER_MODEL` | promptfoo (`llm-rubric` grader) | any OpenAI-compatible gateway; `run-audit.sh` defaults to OpenRouter `anthropic/claude-haiku-4.5` |

## Multi-turn scenarios

A conversation is a run of consecutive tests sharing `conversation_id`, with
descriptions ending in `— turn N`. `evaluateOptions.maxConcurrency: 1` makes
promptfoo run them in order and `cache: false` stops it from replaying stored
replies. The provider appends `EVAL_RUN_ID` to every conversation id. A test
that taps a button sets `button_payload` (the id) and `message` (the title).

Response shape: `reply_text`, `reply_kind` (`text|buttons|list|flow|location|null`),
`buttons[{id,title}]`, `list_rows[{id,title,description}]`, `flow`, `image_url`
(header image of an image + buttons reply, e.g. the clinic location poster; `null`
otherwise), `node_names`, `tool_names`, `agent_run_id`, `agent_run_status`. The
`hasImage` helper in `assertions/custom.js` asserts a non-empty `image_url`;
`datasets/location.yaml` covers the location answer (image + "Cómo llegar" button, the
button tap returning the native location card, and the same after a finished booking).

`datasets/thanks.yaml` covers thanks and short acknowledgements at any point of the conversation: a pure "Gracias" gets a short LLM-written reply with no buttons and never reaches the confusion `fallback` node, a thanks that also requests something keeps its normal routing, and one `requires_real_llm` pair grades the wording (kind, short, no questions, different on two consecutive thanks).

`datasets/flows_view_appointment.yaml` uses the seeded eval patient (Lucía Prueba,
DNI 39000111, two upcoming appointments; `app/infrastructure/dentalink/eval_seed.py`).

`datasets/clinic_topics.yaml` covers the clinic's frequent topics (fixed texts in
`app/agent/clinic_topics.py`): the five topics by free text and by the menu sub-list
(`MENU_FAQ`, then `FAQ_TOPIC:<id>` payloads), a booking phrase that must not reach the
`faq_topic` node, the OSDE / Medifé / William Hope first-visit answer (LLM-written, fact-checked) and "cuánto cubre OSDE"
deriving to administración. Five cases are `requires_real_llm: true` (a paraphrased price
question, a payment paraphrase, a booking phrase and the two-turn insurance scenario). Figures in the texts are pending the clinic's confirmation.

## Production audits

The production endpoint (`https://agent.qeva-ai.com`) is an always-on posture, not a
temporary window (PRD §74.3, "salvo necesidad expresa", behind admin auth):

- `INTERNAL_EVAL_ENABLED=true` and `INTERNAL_EVAL_REAL_LLM=true` live in the
  `agente_ai_backend_env` secret, so the stack needs no extra service variables.
- `POST /internal/eval/chat` is `ADMIN_TECHNICAL` only; every other role gets 403.
- It costs nothing until an admin runs an audit: each turn then spends real LLM budget.

**What the eval turns share with production** (real LLM on): the LLM endpoint
(cost and its logs), one read of the admin runtime LLM config from Postgres (no
writes), the Redis keys `lock:conversation:<eval id>`, `lock:appointment:eval-prof-*:<start>`,
`memory:contact:eval-contact-<eval conversation id>:summary` and the shared read cache `runtime_agent_config`,
and the application logs. Repositories, Dentalink, YCloud, Chatwoot, Telegram,
Linear/incidents, traces and the checkpointer are per-conversation in-memory fakes.
The admin login writes one entry to `admin_audit_log`.

**Single process.** The eval conversation state lives in the memory of one process.
The backend runs one uvicorn process (`entrypoint.sh` has no `--workers`) and the
stack has `replicas: 1`; keep it that way. If the service was ever scaled, run
`docker service scale agente-clinica_backend=1` first, otherwise turns of one
conversation land on different processes and the scenarios break.

### Run an audit

From the repository root, on the production host (Node 20+, `python3`, `curl`):

```bash
evals/run-audit.sh          # add --view to browse the results in the promptfoo UI
```

The script:

- prompts for an `ADMIN_TECHNICAL` user and a silent password (`read -r -s`), sent on
  stdin so it never reaches argv or shell history, and stores the cookies in a
  chmod-600 temp jar that it deletes on exit;
- reads the grader key from `EVAL_GRADER_API_KEY`, or else from the running backend's
  secret file (`LLM_API_KEY`, then `OPENROUTER_API_KEY`), and never prints it;
- pins promptfoo to an exact version (`PROMPTFOO_VERSION` in the script, currently
  `0.123.1`) because it runs with production admin cookies; bump it deliberately after
  checking the release, never with a floating tag;
- prints the approximate session expiry: the admin session lasts
  `ADMIN_SESSION_TTL_SECONDS` (default 3600 s; export the same variable to the script to adjust the printed estimate), so if a long run fails with 401s, re-run;
- grades with `EVAL_GRADER_MODEL` (default `anthropic/claude-haiku-4.5`) at
  `EVAL_GRADER_BASE_URL` (default `https://openrouter.ai/api/v1`);
- runs `npx -y promptfoo@${PROMPTFOO_VERSION} eval` with a run-scoped `EVAL_RUN_ID=audit-<timestamp>`
  (conversation ids never reuse server state), telemetry and sharing disabled, and
  writes `audit-<run id>.json` under `${EVAL_RESULTS_DIR:-$HOME/.cache/agente-ai-evals}`;
- refuses to send an auto-read backend key to any grader host other than `openrouter.ai`
  (an explicit `EVAL_GRADER_API_KEY` may go anywhere);
- exits with promptfoo's code (100 means some tests failed).

`--view` starts `promptfoo view` on `127.0.0.1:${EVAL_VIEW_PORT:-15500}` only (a preload,
`evals/localhost-only.cjs`, overrides promptfoo's default 0.0.0.0 bind) and prints the
tunnel to reach it: `ssh -N -L 15500:localhost:15500 <user>@<host>`.

**Grader cost and limits.** With no `EVAL_GRADER_API_KEY` the grader reuses the production
OpenRouter key, so grading shares its credit and rate limits with the live agent (the
script prints a notice). Prefer a separate `EVAL_GRADER_API_KEY`, for example a dedicated
OpenRouter key with a spend limit. A direct `promptfoo eval` falls back to the same
OpenRouter defaults, but you still must provide the key and cookies; `run-audit.sh` is
the supported path.

`INTERNAL_EVAL_BASE_URL` overrides the target; see `evals/run-audit.sh --help`.

### Turn it off

Remove `INTERNAL_EVAL_ENABLED` and `INTERNAL_EVAL_REAL_LLM` from the secret. Secrets are
immutable, so recreate `agente_ai_backend_env` without those two lines and redeploy the
stack. With `INTERNAL_EVAL_ENABLED` unset the endpoint answers 404 again.

### Cleanup of the temporary secret

Keep `agente_ai_backend_env_eval` until rollback to v0.44.x or earlier (which still
points at it) is no longer needed, for example after the next release. Then remove it:
`docker secret rm agente_ai_backend_env_eval`. Do not remove it right after this
release deploys, or a rollback would fail to start.
