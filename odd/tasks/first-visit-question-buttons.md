# First-visit question with confirm / cancel buttons

## Objective

Before any booking, the agent asks — in a friendly, LLM-built message — whether this is the
patient's first appointment at Smiling Pilar, with two buttons: confirm and cancel.

- Confirm (first visit) → the existing LLM-built single message listing the missing fields
  as "- " bullets (full name, DNI, email, obra social, plan), re-ask until complete, review
  with confirm / modify / cancel, create the patient, then continue the booking flow.
- Cancel (already a patient) → ask full name + DNI (existing identification flow), verify
  the patient exists in Dentalink, then show specialties and run the booking flow.
- Never show specialties before the patient's data is obtained (registered or verified).

## Problem

Observed live on v0.42.2 (2026-09-29): "Agendar una cita" → one message mixing
"¿Es tu primera vez atendiéndote con nosotros?" with the 5-field bullet list, no buttons.
The first-visit question and the data request must be two separate steps.

## Scope

- First step: LLM-built question (static fallback) + 2 buttons (confirm / cancel).
- Confirm → current 5-field intake (PR #143 behavior).
- Cancel → identification by full name + DNI with Dentalink verification, reusing name/DNI
  already known in the conversation (e.g. from a reschedule) instead of asking again.
- Free-text answers ("sí, es la primera", "no, ya soy paciente") behave like the buttons.
- Booking (specialties onward) only after data is obtained.

## Constraints

- Strict TDD: observed RED before implementation, then GREEN, then REFACTOR.
- Runner: `uv run pytest`; also `uv run ruff check .`, `uv run mypy app/`,
  `uv run ruff format --check <changed files>` (repo-wide format check drifts on base).
- Known environmental failures on base: `test_internal_eval_wiring` (1) and
  `test_redis_debounce_lock.py` (3).
- Artifacts in English; patient copy in Spanish. No AI attribution in commits.
- Delivery strategy: ask-on-risk. Push/PR are the user's decision.

## Tasks

- [x] T1 — First-visit question step: LLM-built text + confirm/cancel buttons; confirm →
  5-field intake; cancel → identification (name + DNI, Dentalink check) → specialties.
  Route: delegated direct (writer trigger: 2+ files).

## Acceptance criteria

- "Agendar una cita" → one LLM-built friendly question with 2 buttons, no data list.
- Confirm → the 5-field bullet message; cancel → name + DNI request.
- Cancel with name/DNI already known → verification without asking again.
- Specialties never appear before the data step completes.

## Progress

- Branch `fix/first-visit-question-buttons` from origin/main b80fbce (v0.42.2).
- T1 done (commit: see `git log`, `fix(appointments): ask first-visit question with confirm and cancel buttons`). Route: delegated direct (single writer). TDD: on. Runner: `uv run pytest`.
  - RED (34 failures after adding constants/stub): e.g. `test_offer_asks_the_first_visit_question_with_confirm_and_cancel_buttons`,
    `test_cancelling_the_question_hands_over_to_identification`,
    `test_create_operation_asks_the_first_visit_question_with_confirm_and_cancel_buttons`,
    `test_cancelling_the_first_visit_question_asks_for_name_and_dni_before_specialties`,
    `test_cancelling_with_name_and_dni_already_known_verifies_without_asking_again`,
    `test_a_verified_patient_confirmation_without_a_slot_continues_to_specialties`,
    `test_detect_first_visit_answer_reads_the_question_reply[*]`.
  - GREEN: `uv run pytest tests/unit` 1717 passed; full run only the excused environmental failures.
  - Design: intake subgraph gained a `question` stage (confirm -> collect, cancel/legacy existing payload -> `next_action="identify"`); adapter words the question via intent `first_visit_question`; cancel reuses the identification stage (known name/DNI verified directly, else `_begin_identification`); after verification/registration with no slot picked, booking resumes at specialties (`_continue_booking_with_patient`). Legacy `collect`/`review` checkpoints keep working.
  - Assessed tier / review: RDD off by default; no native review run.

## Next step

User decides push / PR.
