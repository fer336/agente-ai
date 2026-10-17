# Agent pause switch and per-contact allow/deny list

Branch: `feat/agent-pause-switch` (from `main` @ 75ffd73). Delivery strategy: `ask-on-risk`, single PR expected.

## Objective
Let an admin stop the WhatsApp agent from the panel (kill switch), and optionally stop or restrict
specific contacts through a deny list or an allow list.

## Decisions (user)
- Inbound messages are **still persisted** while paused, so the agent has the full context on resume.
- A paused agent sends **nothing on its own**: no replies, welcome, audio fallback, follow-ups or
  appointment reminders. Human staff replies forwarded from Chatwoot are NOT blocked.
- Per-contact control: one list of phone numbers with a mode `off | deny | allow`.
  `deny` = those numbers get no agent answers; `allow` = only those numbers get answers.

## Decisions (assistant, flag in the PR)
- Who can toggle: `ADMIN_TECHNICAL` and `ADMIN_CLINIC` (an emergency stop must not depend on a
  technical user). `READ_ONLY` can only read the state. CSRF + audit log on every change.
- `allow` mode with an empty list is rejected (it would silently silence everybody).
- Phones are compared by digits only (strip `+`, spaces, dashes).
- Shared state lives in the existing single-row `RuntimeAgentConfig` (Postgres + Redis cache,
  10 s TTL, `save_config` invalidates the key), so the bot and admin containers agree.

## Scope (allowed surfaces)
- `app/domain/entities/runtime_agent_config.py`, new pure rule `app/domain/rules/agent_gate.py`
- `app/infrastructure/database/models/runtime_agent_config.py`, its repository, fake, new migration
  `migrations/versions/0023_agent_pause_and_contact_filter.py`
- `app/application/config/runtime_config_service.py` (cache read/write)
- `app/application/messages/ingest_message.py`, `app/application/audio/transcribe_audio.py`,
  `app/workers/follow_up_worker.py`, `app/application/reminders/delivery.py`
- `app/api/routes/admin_llm_config.py` (preserve new fields on PUT), new
  `app/api/routes/admin_agent_control.py`, `app/api/dependencies/config.py`,
  `app/domain/entities/admin_audit_log_entry.py`, `app/main.py` (router registration per role)
- `app/static/admin/*` (new `agent-control.html`, `agent-control.js`, nav links, paused banner)
- `tests/**`, `README.md`, this file

## Tasks
- [x] T1 Domain (0333b5f) + persistence: new fields (`agent_paused`, `paused_by`, `paused_at`,
      `contact_filter_mode`, `contact_filter_phones`), pure `agent_may_respond(config, phone)`,
      model, repository, fake, migration, Redis (de)serialization, `PUT /llm-config` preserves them.
- [x] T2 Gates (3b32756): ingest (welcome + before scheduling + re-check after the debounce sleep +
      audio resume), audio fallback message, follow-up worker, reminder delivery. Messages still saved.
- [ ] T3 Admin API: `GET/PUT /admin/api/agent-control`, validation, roles, CSRF, audit constants,
      router registration for roles `bot|admin|all`, update `tests/unit/test_app_roles.py` route set.
- [ ] T4 Admin UI: control page, pause/resume with confirmation, filter editor, banner on every
      page when paused, nav links, README section.

## Acceptance
- Paused: an inbound text is saved, no agent run is scheduled, no outbound is sent by any worker.
- Message accepted just before the pause but still sleeping in the debounce is NOT answered.
- Resume: the next inbound is answered with the saved history; nothing sent retroactively.
- `deny`/`allow` behave per contact; global pause overrides both.
- Saving the LLM config never changes the pause or filter state.

## Verification
`uv run pytest tests/unit`, `ruff check`, `mypy app`. Known pre-existing failures: 3 tests in
`tests/unit/api/dependencies/test_gateway_dependency.py` (local only).

## Progress
- T1 done (0333b5f): fields, `agent_gate.py`, model/repo/fake/migration 0023, Redis cache, PUT preserves.
- T2 done (3b32756): gates in ingest (welcome, `_schedule_processing`, post-sleep re-check, audio resume),
  audio fallback (via `IngestMessageUseCase.agent_may_respond_to`), follow-up worker (gated actions are
  CANCELLED so nothing is sent retroactively on resume; idle reset is never gated: it sends nothing),
  reminders (gated rows stay pending/untouched; added a guard that retires non-review reminders whose
  appointment already started, since delivery only re-checked identity and there is no send-window
  re-check). Wiring: `agent_gate=get_runtime_config_service().agent_may_respond` in `app/main.py`.
- Verification: `pytest tests/unit` 3837 passed, 3 known failures; ruff check/format and mypy clean.
  Integration test for the SQL roundtrip added but not run (needs DB).
- Next: T3 admin API.
