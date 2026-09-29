# First-visit intake: LLM-built single ask

## Objective

When a patient asks to book ("¿puedo sacar uno?", "quiero sacar un turno"), the agent
sends ONE natural, LLM-built message that asks whether it is their first visit and lists,
as "- " bullets in a fixed order, the missing data: full name, DNI, email, obra social,
plan. Data already known in the conversation is reused, never asked again. The step is
complete only when all 5 fields are present; otherwise the agent re-asks only the missing
ones (LLM-built, same bullet format). Then the existing review with confirm / modify /
cancel runs.

## Problem

Observed live (2026-09-29, v0.42.1): reschedule → name + DNI given → "no encontramos
turnos próximos" → "Puedo sacar uno ?" → static "Hola, soy el asistente de Smiling Pilar.
Antes de ayudarte con tu turno, ¿es tu primera vez en la clínica?" + 2 buttons.

Root causes (origin/main e9d1c08):

1. `_offer_appointments` (`app/agent/nodes/appointment.py:1988-2006`) returns
   `collected_data: {}` on an empty appointment list, discarding the identified patient,
   name and DNI.
2. `_delegate_to_first_visit_intake` (`appointment.py:1503-1518`) builds the intake state
   only from `collected_data["first_visit_intake"]`; the intake starts at `stage="offer"`
   with a static greeting (`app/agent/first_visit_intake_subgraph.py:105-121`).
3. The intake asks one field per turn, stores the whole message as that field, collects
   `phone` instead of `email`, and merges obra social + plan into one `coverage` field
   (`first_visit_intake_subgraph.py:22,49-74,200-224`).

## Scope

- Keep identified patient / full name / DNI when reschedule or cancel finds no appointments.
- Prefill the intake from data already known in `collected_data`.
- Intake fields: `full_name`, `dni`, `email`, `obra_social`, `plan` (this order).
- Ask/re-ask message built by the LLM (existing generation helper, deterministic static
  fallback with the same bullets when the LLM fails). No greeting, no first-visit buttons.
- Extract several fields (and the first-visit answer) from one free-text reply.
- Review summary shows the 5 fields; confirm / modify / cancel unchanged.
- Persistence: obra social + plan feed the existing agreement match; email passed on if
  the gateway supports it; phone comes from the WhatsApp contact, not asked.

## Constraints

- Strict TDD: observed RED before implementation, then GREEN, then REFACTOR.
- Runner: `uv run pytest` (source: session Strict TDD Mode). Also `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy app/`.
- Artifacts in English; patient-facing copy in Spanish (Rioplatense, as existing copy).
- Delivery strategy: ask-on-risk. Commits on `fix/first-visit-intake-llm`; push/PR are
  the user's decision.

## Assumptions (pending user confirmation)

- A patient already identified in Dentalink is still asked the first-visit question; the
  known name and DNI are prefilled so only the missing fields are listed.

## Tasks

- [x] T1 — Preserve identity on empty reschedule/cancel results and prefill the intake
  from known `collected_data`. Route: delegated direct (writer trigger: 2+ files).
- [x] T2 — Intake rewrite: 5 fields, multi-field extraction, LLM-built single ask and
  re-ask with static fallback, review with 5 fields. Route: delegated direct.
- [ ] T3 — Persistence adapts to `obra_social` / `plan` / `email` and the contact phone.
  Route: delegated direct.

## Acceptance criteria

- The chat from the Problem section produces one LLM message listing only email,
  obra social and plan (name + DNI reused), with no greeting.
- A reply with some fields re-asks only the missing ones; all 5 → review with
  confirm / modify / cancel.
- LLM failure falls back to a static message with the same ordered bullets.

## Progress

- Worktree: `/home/lucy/work/agente-ai-worktrees/first-visit-intake-llm` from origin/main e9d1c08.
- Baseline on untouched base (`uv sync --extra dev`; `uv run pytest`): 4 failed + 3 errors, all environmental: `tests/integration/test_internal_eval_wiring.py::test_get_evaluate_chat_turn_use_case_wires_a_working_isolated_agent` and the 3 `tests/integration/test_redis_debounce_lock.py` tests (no Redis). `test_gateway_dependency.py` passes here.
- T1 done. RED: `test_no_appointments_keeps_identity_and_clears_the_stale_operation_stage`, `test_first_visit_intake_is_prefilled_from_the_identified_patient`, updated `test_identification_stage_reports_no_appointments_for_cancel` failed before the change; GREEN after (`uv run pytest tests/unit`: 1645 passed). Commit: see git log (`fix(appointments): keep patient identity when no appointments are found`).

## Next step

T3.

- Note: `uv run ruff format --check .` already reports 82 files on the untouched base (installed ruff 0.16.1 drift); changed hunks were checked with `ruff format --diff` and add no new drift. Repo-wide format is not applied to avoid unrelated churn.
- T1 commit: 6cc4019.
- T2 done. Approach: subgraph stays pure (validates/merges `extracted_details`, returns `ask_fields` + static fallback text); new `app/agent/first_visit_intake_extraction.py` extracts email/DNI/first-visit answer deterministically and full name/obra social/plan via the existing `LLMProvider.extract_information` (no new provider capability; lone obra social/plan answer taken verbatim only if the LLM errors; a name is never guessed). Ask wording: `generate_or_fallback` with new intent `first_visit_intake_ask` (intro only) + "- " bullets appended verbatim, so field list/order cannot drift. Bridge kept for T3: coverage string = obra social + plan; phone = WhatsApp contact.
  RED: 8 subgraph tests failed, extraction module ImportError, 7 node tests + 5 invoker tests failed before implementation (e.g. `test_asking_to_book_after_a_reschedule_without_appointments_reuses_name_and_dni`). GREEN: `uv run pytest` 1675 passed, only the baseline environmental failures remain; ruff check and mypy clean.
