# Fixed text for interactive steps

Branch: `feat/fixed-text-interactive-steps` (based on `fix/specialty-and-slot-asks-stay-on-script`, commit `28d42ef`, reviewed, not pushed).

## Objective
Every step that sends WhatsApp buttons, a list or a Flow uses its fixed, tested text. The LLM only words free-form replies (answers to questions, thanks, handoff wording).

## Problem
`gemini-3.5-flash-lite` ignores prompt rules when it words the text above buttons and lists. Observed live (2026-10-15): greeting on every message, the "symptoms must be evaluated by a professional" disclaimer on unrelated steps, offers of administration above a specialty list, and "He registrado tu solicitud" before the patient taps Confirmar. The previous messages are fed back as assistant turns, so the first improvised text becomes a template for the next ones.

## Why
Texts that accompany buttons must match them exactly, and an action must never be claimed before the confirmation button. Per-step validators are too narrow (about 30 steps remain) and weak (substring checks).

## Scope
- Make interactive steps in `app/agent/nodes/appointment.py` and `app/agent/appointment_decision_subgraph.py` (and any other file the mapping finds) send their fixed text.
- Extend `app/agent/action_claims.py` so "registré / he registrado tu solicitud" counts as a claim.
- Keep the LLM for free-form answers, thanks, fallback and handoff wording.

## Out of scope
- Free-form and handoff wording keep the LLM: agreement.py answers, question.py, thanks/close replies, create/reschedule/cancel success wording, fallback.py:202, payment_admin.py:35, resolve_interaction.py:617, subgraph specialty_retry_escalation.
- Text-only steps without buttons (session_lost, proposal_*, slot_taken) stay LLM-worded for now.
- `understand` robustness with `gemini-3.5-flash-lite` (7 of 16 promptfoo cases failed with invalid JSON) and the unguarded call at `resolve_interaction.py:700`.
- Google key quota (429), model choice, temperature.

## Constraints
- English artifacts; patient-facing Spanish texts stay as they already are.
- Test first (RED then GREEN) where a runnable test exists.
- About 400 authored lines per task is a planning heuristic only.
- Push, PR and merge are the user's decisions.

## Route declaration
- T0 mapping: delegated read-only explorer (trigger: more than ~5 lookups across two large files).
- T1: inline (one small file plus its test, no research needed).
- T2/T3: delegated writer (2+ non-trivial files).

## Tasks
- [x] T0 Map every `generate_or_fallback` call: interactive or free-form, validator, fixed fallback. Evidence: explorer table, 78 call sites (53 appointment.py, 13 subgraph, 12 other nodes); ~45 interactive without validator.
- [x] T1 Action-claim guard catches "registré/registrado ... solicitud". Evidence: 4 new claim cases RED then GREEN, 3 pending-wording cases stay false; `tests/unit/agent` 1685 passed.
- [x] T2 Interactive steps in `appointment.py` send fixed text (propose_* x4, send_*_flow x3, no_slots, choose_slot x2, no_appointments, view summary, patient_not_found, confirmation_reminder x4, stale_* x4, view_action_reminder, operation_selection_reminder, operation_menu, variable-intent sites). Evidence: writer converted 34 call sites; 17 new tests with an improvising LLM (RED then GREEN) in `tests/unit/agent/nodes/test_fixed_interactive_text.py`; parent spot check `tests/unit`: 3651 passed, 3 known failures.
- [x] T3 Interactive steps in `appointment_decision_subgraph.py` send fixed text (choose_browse_mode, browse_mode_reminder, specialty_retry, no_slots, choose_slot x2, stale_slot_selection, variable-intent site). Evidence: same writer run (4 subgraph steps covered by tests; `operation_selection_reminder`, `view_action_reminder` and `propose_verification_confirmation` converted without a dedicated test).
- [ ] T4 Re-run promptfoo `flows.yaml` with the real LLM on the final branch and record results.

## Acceptance criteria
- With a model that answers every request off-script, no interactive step shows model text.
- `claims_executed_action("He registrado tu solicitud para el viernes...")` is true.
- Free-form steps still use the LLM.
- Full unit suite green except the 3 known failures in `tests/unit/api/dependencies/test_gateway_dependency.py`.

## Progress
Branch created. T0-T3 done; T4 (promptfoo with real LLM) pending.

## Verification evidence
Writer: `uv run pytest tests/unit/agent -q` 1701 passed; ruff and mypy clean. Parent spot check: `uv run pytest tests/unit -q` 3651 passed, 3 failed (known `test_gateway_dependency.py`); ruff check and mypy app/agent clean. Remaining model-worded calls: 27 in appointment.py, 5 in the subgraph (validated steps, success/close wording, session_lost, proposals, slot_taken).

Behaviour changes to confirm: `no_appointments` fixed text offers administration so the result now carries `HANDOFF_OFFER_KEY`; the cancel proposal no longer greets the patient by name; deleted test `test_the_confirmation_reminder_instruction_only_asks_to_use_the_buttons` (it asserted an LLM instruction that no longer exists).

## Next step
T4: re-run promptfoo `flows.yaml` with the real LLM (needs the user's authorization for the Google key again).
