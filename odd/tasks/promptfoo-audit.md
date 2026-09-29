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
- [ ] T3 — Multi-turn datasets and assertions for recent flows.
- [ ] T4 — First local promptfoo run and findings report.

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

## Next step

T1 commit, then T2.
