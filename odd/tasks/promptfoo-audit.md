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
- [ ] T2 — Expose buttons, list rows and the flow marker in the eval response.
- [ ] T3 — Multi-turn datasets and assertions for recent flows.
- [ ] T4 — First local promptfoo run and findings report.

## Progress

- Branch `feat/promptfoo-audit` from origin/main 944affc (v0.43.0).
- T1: applied the pending diff from `fix/internal-eval-reply` unchanged.
  `uv run pytest tests/unit/application/admin/test_evaluate_chat_turn.py`: 8 passed; ruff
  check, ruff format --check and mypy clean.

## Next step

T1 commit, then T2.
