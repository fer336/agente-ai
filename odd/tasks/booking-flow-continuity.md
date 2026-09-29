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
- [x] T2 — No greetings mid conversation in LLM answers.
- [x] T3 — Handoff offer with Administración / Menú principal buttons; main menu resets
  workflow state but keeps identity.
- [x] T4 — Varied LLM-built intake re-ask intros.

## Acceptance criteria

- Chat A replays: slot pick → booking confirmation (no identity re-ask, no "no turnos").
- A mid-conversation LLM answer never starts with a greeting.
- The handoff offer shows the 2 buttons. "Menú principal" restarts the flow with name/DNI kept.
- Two consecutive re-asks do not share the same intro.

## Progress

- Branch `fix/booking-flow-continuity` from origin/main 651e254 (v0.42.3).

- T1 done. Root causes: (a) `app/agent/nodes/appointment.py` identification stage decided "create vs lookup" only from `collected_data["operation"] == CREATE` (was line ~3850, also the verification-confirmation and registration-flow twins), so a picked slot whose `operation` key was not carried fell into `_offer_appointments` ("no encontramos turnos próximos"); now `_is_create_flow` also treats `pending_selected_slot` as a booking, and both slot-pick exits force `operation=create`. (b) Identity lived only in `collected_data`, which every reset (`_welcome_reset_response`, `{}` returns) replaces, so a verified/registered patient was asked again; now `AgentState["patient_identity"]` (new, top-level, checkpointed, seeded by the invoker) survives resets and is injected as `patient` + `first_visit_completed` on entry, so booking, slot pick and reschedule/cancel/view skip re-identification. Not reproduced with the exact live chat (the live LLM path is not replayable); the reproducible defects above are fixed and covered. Known limit: a successful booking rotates the workflow session (new checkpoint thread), which still drops the remembered identity (open question).
  RED: `test_the_picked_slot_and_create_operation_survive_identification`, `test_identification_with_a_picked_slot_never_takes_the_no_appointments_path` (no_appointments intent taken), `test_a_remembered_patient_is_not_asked_for_identification_after_picking_a_slot`, `..._skips_the_first_visit_question_when_booking_again`, `..._to_view_appointments`, `test_identifying_a_patient_reports_the_identity_to_remember` (KeyError patient_identity), invoker `test_a_verified_patient_is_remembered_across_a_main_menu_reset_until_the_thread_ends`. GREEN: `uv run pytest` 1744 passed + baseline environmental failures; ruff check and mypy clean. Rejecting a verified record ("no soy yo") now also drops it from `collected_data` so it is never remembered.

- T2 done. Origin of the live greeting: the question answer comes from `understand()`'s free-text `answer` field (`pending_answer`, delivered verbatim by the question/fallback nodes), whose prompt had no anti-greeting rule; `generate_response` already forbade greetings. Fix: `ResponseContext.conversation_started` (assistant already spoke, from `recent_messages`) drives an appended "La conversación ya empezó" instruction in `generate_response` and in `understand` (context key set by `resolve_interaction`), the `answer` field rule now forbids greeting, and `strip_leading_greeting`/`without_mid_conversation_greeting` (`app/agent/nodes/llm_response.py`) strip a leading greeting from every `generate_or_fallback` result and from `pending_answer` in the question/fallback nodes. The first reply of a conversation may still greet.
  RED: `test_llm_response.py` (ImportError), `test_question_answer_never_greets_mid_conversation`, `test_fallback_delivers_a_pending_answer_without_a_mid_conversation_greeting`, provider prompt tests, `test_understand_is_told_whether_the_conversation_already_started`. GREEN: `uv run pytest` 1763 passed + baseline environmental failures; ruff check and mypy clean.

- T3 done. No structured signal exists for the offer (`understand()` returns prose only), so `app/agent/handoff_offer.py` detects it deterministically (administración + an offer verb). Question node (LLM answer and the "no confirmed answer" reply) and the fallback node's `pending_answer` now send `HANDOFF_OFFER_BUTTONS` (💬 Administración = `MENU_ADMIN_PAYLOAD`, Menú principal = `MENU_MAIN_PAYLOAD`) and set the one-turn `handoff_offer_pending` flag; `resolve_interaction` turns a short agreement ("bueno", "dale", "sí", "ok"...) with that flag into the same `handoff`/`terminate` result as the button, and strips the flag every turn. Typed "menú principal" (and "volver al menú"...) is recognised deterministically in `resolve_interaction` (carries `navigation_target=main`) and in the appointment node, which resets via the same `_welcome_reset_response` as the button; `collected_data` (stage, operation, pending action id, intake, slots) is cleared while `AgentState["patient_identity"]` (T1) keeps the patient until the thread ends (idle rotation or admin reset). Not applied: the reschedule/cancel "no appointments" reply still has no buttons (open question).
  RED: `test_handoff_offer.py` (ModuleNotFoundError), question/fallback button tests, the 4 acceptance tests + `test_the_handoff_offer_only_lives_for_one_turn`, `test_the_main_menu_resets_the_workflow_state_however_it_is_requested[typed]`. GREEN: `uv run pytest` 1801 unit passed; ruff check and mypy clean.

- T4 done. Origin of the repeat: the LLM, not the static fallback. The live sentence "Buenísimo, gracias por la info. Todavía me faltan…" is not any static text (`RETRY_ASK_INTRO` read "Gracias. Todavía me faltan estos datos:"); the ask was generated with the same situacion/instruccion on every turn, no previous intro and the configured (low) temperature. Fix: `_first_visit_ask_message` (`app/agent/nodes/appointment.py`) now passes `intro_anterior` and a "no repitas su apertura" instruction, samples at 0.9 through the new per-call `ResponseContext.temperature` (`generate_or_fallback(temperature=...)`, honoured by the OpenAI-compatible provider), and if the model still opens like the previous ask (`repeats_opening`, first two words) it uses the static fallback. The static fallback is now 4 phrasings per ask kind (`app/agent/first_visit_intake_wording.py`) rotated so it never opens like the previous intro; the defensive "still missing" branch uses the same rotation. Previous intro = text before the bullets of the last assistant message.
  RED: `test_first_visit_intake_wording.py` (ImportError), `test_consecutive_re_asks_do_not_repeat_the_intro_even_if_the_llm_does`, `test_the_intake_ask_tells_the_llm_the_previous_intro_and_asks_for_variety`, `test_static_fallback_intros_of_consecutive_re_asks_differ`, `test_generate_response_honours_a_per_call_temperature`. GREEN: `uv run pytest` unit suite passes; ruff check and mypy clean.

## Next step

Ready for user review (push/PR are the user's decision). Open questions: identity is lost when a booking succeeds (workflow session rotation starts a new checkpoint thread); reschedule/cancel "no appointments" reply has no handoff buttons.
