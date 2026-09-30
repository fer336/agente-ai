# Promptfoo audit

## Objective

Audit the WhatsApp agent end to end with promptfoo through the isolated
`/internal/eval/chat` endpoint. The endpoint path is FastAPI → LangGraph → fake Dentalink →
fake YCloud, so no real patient data or WhatsApp traffic is involved. Cover the multi-turn
flows fixed recently, so every PR can be audited before deploy.

## Problem

- `evals/promptfooconfig.yaml` and 6 datasets exist but were never executed.
- The eval endpoint returns `reply_text: null` for interactive replies (buttons, lists,
  flows), and it never exposes button titles or list rows. Assertions can't check the
  button-driven flows.
- The recent bugs only show up across several turns: first visit, identity continuity,
  mid-conversation greetings, handoff buttons, "Ver mi cita".

## Scope

- T1: read the reply text from interactive replies too. This is the user's pending change
  from `fix/internal-eval-reply`, moved onto current main.
- T2: expose the interactive options in the eval response: button ids and titles, list rows,
  and the flow marker.
- T3: make the datasets multi-turn with a shared `conversation_id`, and add assertions
  for the recent flows.
- T4: run promptfoo locally against a dev server (never production) and report the
  findings.

## Constraints

- Never point the evals at production. This host also runs the production Swarm stack
  (`agente-clinica_backend`, Chatwoot), so local runs must not touch those containers,
  ports or databases.
- Strict TDD for app code; runner `uv run pytest`; also `uv run ruff check .`,
  `uv run mypy app/`, `uv run ruff format --check <changed files>`.
- Known environmental failures: `test_internal_eval_wiring` (1), `test_redis_debounce_lock.py` (3).
- English artifacts; patient-facing test messages in Spanish. No AI attribution in commits.
- Delivery: `docs/pr-release-workflow.md`.

## Tasks

- [x] T1 — Interactive reply text in eval results (user's change from `fix/internal-eval-reply`).
  Route: direct inline (already written and tested).
- [x] T2 — Expose buttons, list rows and the flow marker in the eval response, plus an
  optional `button_payload` request field so a test can tap a button. Route: direct inline.
- [x] T2b — (discovered) Keep conversation state across eval turns. The endpoint built a whole
  new stack (fake repos, `MemorySaver()` per turn, patient fakes) on every request, so turn 2
  never saw turn 1 and multi-turn scenarios were impossible. Added `EvalSessionRegistry`
  (per-conversation, LRU 256) + `get_eval_use_case_provider`, one shared `MemorySaver` per stack,
  and the use case now consumes the gateway's captured replies after each turn. Route: direct inline.
- [x] T3 — Multi-turn datasets and assertions for recent flows. Route: direct inline
  (evals-only files; no app code).
- [ ] T4 — First local promptfoo run and findings report. Prepared only: runbook in
  `evals/README.md`; the run itself is pending the user's go-ahead.
- [x] T5 — `INTERNAL_EVAL_REAL_LLM` opt-in: the eval stack uses `get_llm_provider()` (same
  provider and admin runtime LLM config as the webhook path) instead of `FakeLLMProvider`.
  Route: direct inline.
- [x] T6 — Seed an eval patient with 2 upcoming appointments; enable `flows_view_appointment.yaml`.
  Route: direct inline.
- [x] T7 — Refresh stale dataset expectations for the real LLM; production-run runbook.
  Route: direct inline (generated datasets + README).

## Progress

- Branch `feat/promptfoo-audit` from origin/main 944affc (v0.43.0).
- T1: applied the pending diff from `fix/internal-eval-reply` unchanged.
  `uv run pytest tests/unit/application/admin/test_evaluate_chat_turn.py`: 8 passed; ruff
  check, ruff format --check and mypy clean.
- T2: RED = collection ImportError (`EvalFlow`/`EvalOption` missing) in
  `test_evaluate_chat_turn.py` and `test_internal_eval.py`; new tests:
  `test_execute_exposes_reply_buttons_with_their_ids_and_titles`,
  `..._list_rows_flattened_across_sections`, `..._the_flow_marker`,
  `..._plain_text_reply_kind_without_options`, `..._prefers_the_interactive_reply_over_a_preceding_text`,
  `..._forwards_the_button_payload_to_the_agent_invoker`,
  `test_button_payload_is_threaded_into_the_use_case`, `test_response_exposes_interactive_options`.
  GREEN: `uv run pytest tests/unit` 1869 passed; ruff check and mypy clean. The two T1
  interactive-reply tests used `object()` placeholders; now real `FlowRequest`/`ListMessage`.
- Response shape: `reply_kind`, `buttons[{id,title}]`, `list_rows[{id,title,description?}]`,
  `flow{flow_id,screen_id,cta}|null`; interactive replies win over a preceding plain text.
- T2b: RED = ImportError `EvalSessionRegistry`. Tests: registry reuse/LRU/provider in
  `test_internal_eval_dependency.py`, `test_a_button_tap_on_turn_two_continues_the_conversation_of_turn_one`
  (real graph, `InMemoryFakeRedis`), drain test in `test_evaluate_chat_turn.py`. Full
  `uv run pytest`: 1881 passed, 83 skipped, only the 3 excused redis_debounce failures.
- Commits: T1 045a646, T2 fed36cc, T2b 7e9b04c.
- Empty `button_payload` (promptfoo renders an unset var as "") is treated as no tap. RED:
  `test_an_empty_button_payload_is_treated_as_no_tap` (`'' is None`).
- T3: `evaluateOptions.maxConcurrency: 1` + `cache: false`; provider body appends `EVAL_RUN_ID`
  to `conversation_id` and sends `button_payload`. Test paths changed to `file://datasets/...`
  (resolved from the config dir; `evals/datasets/...` would resolve to `evals/evals/...`).
  New `evals/datasets/flows.yaml` (5 scenarios, 12 turns) and `flows_view_appointment.yaml`
  (scenario 6, not enabled: the eval stack seeds no patient/appointments). New helpers in
  `assertions/custom.js`. Scaffold test: `uv run pytest tests/unit/evals` 35 passed
  (RED first: 12 failed before the datasets/config existed).
- Offline replay of `flows.yaml` against the real graph (in-process, fake LLM, `InMemoryFakeRedis`):
  all deterministic asserts pass; the `requires_real_llm: true` ones fail on the
  `[fake-response ...]` placeholder by design.
- Stale expectations fixed: `appointments` 01 (now opens with the first-visit question) and 05
  (now a 3-turn flow: Agendar, Cancelar, then name + DNI). Others listed in the final report.
- Finding: the eval endpoint always uses `FakeLLMProvider`; LLM wording cannot be audited until
  the endpoint can opt in to the real LLM (decision pending).
- Decisions (2026-09-30): real-LLM opt-in YES; the audit runs against PRODUCTION
  (https://agent.qeva-ai.com) with the vars added temporarily to the Swarm secret (PRD §74.3
  "salvo necesidad expresa").
- T5: RED = `test_internal_eval_real_llm_is_off_by_default_and_read_from_env` (no attribute),
  `..._uses_the_webhook_llm_provider_when_the_real_llm_is_opted_in` (still FakeLLMProvider),
  `test_real_llm_opt_in_without_an_llm_url_fails_loudly_instead_of_faking` (DID NOT RAISE).
  GREEN: `uv run pytest` 1899+ passed (only the 3 excused redis failures), ruff check and mypy clean.
  Opt-in with an empty `LLM_API_URL` returns 503 instead of silently faking.
- T5 shared with production when the flag is on: Redis keys `lock:conversation:<eval id>`,
  `lock:appointment:<professional id>:<start>`, `memory:contact:eval-contact:summary`
  (10 s-ish cache), `runtime_agent_config` (shared read cache of the admin LLM config);
  Postgres: one read of the runtime LLM config (no writes); the real LLM endpoint (cost, its
  own logs); app logs. Everything else (repos, checkpointer, Dentalink, YCloud, Telegram,
  Linear, incidents, errors, traces) is per-conversation in-memory fakes.
- T6: RED = ModuleNotFoundError `app.infrastructure.dentalink.eval_seed`. New `eval_seed.py`
  (`build_eval_seed(now)`, ids prefixed `eval-`), `FakeDentalinkGateway(appointments=...)` param,
  seed used only by `get_evaluate_chat_turn_use_case`. Patient "Lucía Prueba", DNI 39000111
  (not the 30111222 that `appointments-05` expects to be not found). Verified in-process:
  "Lucía Prueba, 39000111" returns the 2-line summary with the 3 buttons. Note: the FAKE
  LLM's name extraction fails on "..., DNI 39000111", so the dataset omits the "DNI" word.
- T7: rewrote `appointments.yaml` (02, 03, 07, 08 multi-turn through the seeded booking,
  reschedule and cancel flows; 04 tagged; 06 and 09 removed with a comment: not reproducible),
  `safety.yaml` (03 and 04 multi-turn), `audio.yaml` (02 to 07 multi-turn at the state they
  describe). New helper `hasOptionIds` proves the agent offers only seeded slots/appointments
  and that typed text never advances a gate. Offline replay against the real graph (fake LLM):
  all 53 deterministic asserts of these datasets pass. Wording asserts are tagged
  `requires_real_llm: true`. `evals/README.md` gained "Run against production".
  `uv run pytest tests/unit/evals`: 38 passed.

## Next step

T4: the user enables the env vars in the production secret and runs the audit (runbook in `evals/README.md`); then triage the findings.
