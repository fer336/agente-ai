# Booking flow continuity

## Objective

Booking keeps its context end to end. The agent never re-asks identity data it already has,
never switches from "book" to "look up existing appointments", never re-greets mid
conversation, offers explicit buttons when it proposes a handoff to administration, and
words every intake re-ask with the LLM so it never sounds mechanical.

## Problem

Observed live on v0.42.3 (2026-09-29).

Chat A:
1. The patient picks a slot ("Vie 02/10 11:15").
2. The agent asks for full name + DNI "así te registro", although the same patient
   (Fernando) registered minutes earlier.
3. The patient answers "Pedro cassera 30131313".
4. The agent answers "no encontramos turnos próximos disponibles para vos". That wording
   comes from the no-existing-appointments path (`app/agent/nodes/appointment.py:2223`, used
   for reschedule/cancel/view), so the create operation was lost after identification.
5. "Por?" gets an answer about the reason for the visit. "Para un tratamiento particular"
   gets "¡Hola! Sí, atendemos pacientes particulares. Si querés, puedo pasarte con
   administración…". That is a re-greeting mid conversation, and the handoff offer comes
   without buttons.
6. "Bueno" falls to the fallback "Perdón, no te entendí" with the Agendar/Administración
   buttons.

Chat B: the intake re-asks start with the same "Buenísimo, gracias por la info. Todavía me
faltan…" on consecutive turns.

## Scope

- T1: after a slot is picked, never ask identity again when the patient was registered or
  verified earlier in the conversation. When identification is needed, the create
  operation and the picked slot survive it, and booking continues to the confirmation. The
  "no appointments" path only runs for reschedule/cancel/view.
- T2: LLM free-text answers (question/general nodes) never greet ("Hola", "¡Hola!") after
  the first turn of a conversation.
- T3: when the LLM offers a handoff to administration, the message carries 2 buttons:
  "💬 Administración" and "Menú principal". "Menú principal" resets the agent's workflow
  state (graph/stage/operation) and keeps the patient identity (full name, DNI, verified
  patient) until the conversation ends (idle reset / admin reset). Accepting in free text
  ("bueno", "dale", "sí") after that offer behaves like the Administración button.
- T4: every intake ask/re-ask intro is LLM-built and varied. Do not repeat the previous
  intro; the static fallback rotates between several phrasings.

## Constraints

- Strict TDD: observed RED before implementation, then GREEN, then REFACTOR.
- Runner: `uv run pytest`; also `uv run ruff check .`, `uv run mypy app/`,
  `uv run ruff format --check <changed files>`.
- Known environmental failures: `test_internal_eval_wiring` (1), `test_redis_debounce_lock.py` (3).
- English artifacts, Spanish patient copy, no AI attribution in commits.
- Delivery: see `docs/pr-release-workflow.md` (squash, `fix(...)` title). Push and PR only
  when the user asks.

## Tasks

- [x] T1 — Keep the create operation and identity through identification after a slot pick.
- [ ] T2 — No greetings mid conversation in LLM answers.
- [ ] T3 — Handoff offer with Administración / Menú principal buttons; main menu resets
  workflow state but keeps identity.
- [ ] T4 — Varied LLM-built intake re-ask intros.

## Acceptance criteria

- Chat A replays: slot pick → booking confirmation (no identity re-ask, no "no turnos").
- A mid-conversation LLM answer never starts with a greeting.
- The handoff offer shows the 2 buttons. "Menú principal" restarts the flow with name/DNI kept.
- Two consecutive re-asks do not share the same intro.

## Progress

- Branch `fix/booking-flow-continuity` from origin/main 651e254 (v0.42.3).

- T1 done. Root causes: (a) `app/agent/nodes/appointment.py` identification stage decided "create vs lookup" only from `collected_data["operation"] == CREATE` (was line ~3850, also the verification-confirmation and registration-flow twins), so a picked slot whose `operation` key was not carried fell into `_offer_appointments` ("no encontramos turnos próximos"); now `_is_create_flow` also treats `pending_selected_slot` as a booking, and both slot-pick exits force `operation=create`. (b) Identity lived only in `collected_data`, which every reset (`_welcome_reset_response`, `{}` returns) replaces, so a verified/registered patient was asked again; now `AgentState["patient_identity"]` (new, top-level, checkpointed, seeded by the invoker) survives resets and is injected as `patient` + `first_visit_completed` on entry, so booking, slot pick and reschedule/cancel/view skip re-identification. Not reproduced with the exact live chat (the live LLM path is not replayable); the reproducible defects above are fixed and covered. Known limit: a successful booking rotates the workflow session (new checkpoint thread), which still drops the remembered identity (open question).
  RED: `test_the_picked_slot_and_create_operation_survive_identification`, `test_identification_with_a_picked_slot_never_takes_the_no_appointments_path` (no_appointments intent taken), `test_a_remembered_patient_is_not_asked_for_identification_after_picking_a_slot`, `..._skips_the_first_visit_question_when_booking_again`, `..._to_view_appointments`, `test_identifying_a_patient_reports_the_identity_to_remember` (KeyError patient_identity), invoker `test_a_verified_patient_is_remembered_across_a_main_menu_reset_until_the_thread_ends`. GREEN: `uv run pytest` 1748 passed + baseline environmental failures; ruff check and mypy clean. Rejecting a verified record ("no soy yo") now also drops it from `collected_data` so it is never remembered.

## Next step

T2.
