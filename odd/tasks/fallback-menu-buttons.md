# Fallback menu buttons: reuse the main-menu actions

## Objective
When the bot does not understand a message, it offers only actions that lead straight into a working flow:
- `📅 Agendar una cita` goes straight to the specialty list.
- `💬 Administración` hands the patient to staff.

The legacy "Turnos" / "Especialidades" / "Administración" buttons are removed.

## Problem
- The fallback reply (`app/agent/nodes/fallback.py`, `_MAIN_MENU_BUTTONS`) sends the buttons "Turnos" (`MENU_APPOINTMENT`), "Especialidades" (`MENU_SPECIALTIES`) and "Administración" (`MENU_ADMIN`). The user no longer wants "Turnos" or "Especialidades".
- The escalation after repeated invalid picks (`app/agent/appointment_decision_subgraph.py`, `_ESCALATION_BUTTONS`) uses a plain "Administración" button.

## Scope / constraints (user decisions, 2026-09-23)
- Remove the "Turnos" and "Especialidades" buttons. Replace "Turnos" with `📅 Agendar una cita`, which reuses `OPERATION_CREATE` (the same payload as the main-menu list row) and must open the specialty list directly.
- A confused patient (fallback) is asked whether they want to talk to administration and is shown `💬 Administración` (payload `MENU_ADMIN`). This replaces every plain "Administración" button, including the subgraph escalation.
- The button text is `💬 Administración` (17 chars, within WhatsApp's 20-char button cap). "💬 Hablar con un asesor" (22 chars) is kept only as the main-menu list row, where the cap is 24.
- Cancel, reschedule and book are understood from free text by the LLM intent layer; no extra buttons for them. Verify the existing coverage and report gaps; do not invent a new classifier.
- `MENU_APPOINTMENT` / `MENU_SPECIALTIES` payloads remain routable (old messages in chat history can still be tapped).
- TDD: strict. Runner: `uv run pytest`, plus `ruff check` and `mypy app`.
- Branch: `fix/slot-list-duplicate-row-ids` (PR #127). The user wants everything merged together.

## Tasks
- [x] T1 Fallback buttons become `📅 Agendar una cita` (`OPERATION_CREATE`) and `💬 Administración` (`MENU_ADMIN`). Update the fallback LLM context (`opciones_del_menu`) and the reply so a confused patient is asked whether they want to talk to administration. Route: delegated.
- [x] T2 The subgraph escalation button "Administración" becomes `💬 Administración`. Route: delegated (same writer).
- [ ] T3 Verify that `OPERATION_CREATE` sent from the fallback button opens the specialty list directly, and that free-text cancel / reschedule / book reach the appointment flow. Add regression tests; report any gap. Route: delegated (same writer).

## Acceptance criteria
- No outbound message contains a "Turnos", "Especialidades" or plain "Administración" button.
- The fallback shows exactly `📅 Agendar una cita` and `💬 Administración`, and its text asks whether the patient wants to talk to administration.
- Tapping `📅 Agendar una cita` from the fallback returns the specialty list.
- The full test suite (except the 5 known pre-existing failures), ruff and mypy pass.

## Progress / evidence
- 2026-09-23: Scope agreed with the user. Button text decided: `💬 Administración`.
- 2026-09-23 T1 (route: delegated, single writer, strict TDD):
  - RED: updated `tests/unit/agent/nodes/test_fallback_node.py` to expect
    `[OPERATION_CREATE_PAYLOAD, MENU_ADMIN_PAYLOAD]` / `["📅 Agendar una
    cita", "💬 Administración"]` first — `uv run pytest -q
    tests/unit/agent/nodes/test_fallback_node.py` failed 3/15
    (`test_fallback_node_shows_the_book_and_administracion_buttons`,
    `..._falls_back_to_a_static_message...`,
    `test_a_pending_answer_is_delivered...`).
  - GREEN: `app/agent/nodes/fallback.py` — renamed `_MAIN_MENU_BUTTONS` ->
    `_CONFUSED_PATIENT_BUTTONS` (`OPERATION_CREATE_PAYLOAD` + `📅 Agendar
    una cita`, `MENU_ADMIN_PAYLOAD` + `💬 Administración`), renamed
    `_MAIN_MENU_MESSAGE` -> `_CONFUSED_PATIENT_MESSAGE`, updated
    `opciones_del_menu` and the base `instruccion` (2 botones, no literal
    "administración" in the base instruction — keeps
    `test_first_fallback_never_tells_the_llm_to_escalate` honest, only the
    repeat-miss `instruccion_extra` names it explicitly). `uv run pytest -q
    tests/unit/agent/nodes/test_fallback_node.py` -> 15 passed.
  - `uv run ruff check app/agent/nodes/fallback.py
    tests/unit/agent/nodes/test_fallback_node.py` -> All checks passed.
    `uv run mypy app/agent/nodes/fallback.py` -> Success.
  - Commit: `b39876d` (`fix(agent): swap fallback buttons for book+administracion actions`).

- 2026-09-23 T2 (route: delegated, single writer, strict TDD):
  - Swept `app/` with `rg -n "InteractiveButton\("... title="Administr"` —
    confirmed only 2 plain "Administración" buttons existed:
    `app/agent/nodes/fallback.py` (fixed in T1) and
    `app/agent/appointment_decision_subgraph.py:223`'s
    `_ESCALATION_BUTTONS`. No other plain "Administración" button found.
  - RED: added a title assertion (`admin_button.title == "💬 Administración"`)
    to both `test_a_second_invalid_specialty_choice_escalates_to_administracion`
    and `test_a_second_invalid_professional_choice_escalates_to_administracion`
    in `tests/unit/agent/test_appointment_decision_subgraph.py` — `uv run
    pytest -q tests/unit/agent/test_appointment_decision_subgraph.py -k
    escalates_to_administracion` failed both (`'Administración' ==
    '💬 Administración'`).
  - GREEN: `app/agent/appointment_decision_subgraph.py:223` — `_ESCALATION_BUTTONS`'
    admin button title -> `"💬 Administración"` (same `MENU_ADMIN_PAYLOAD`).
    `uv run pytest -q tests/unit/agent/test_appointment_decision_subgraph.py`
    -> 50 passed. `uv run pytest -q tests/unit/agent` -> 320 passed.
  - `uv run ruff check app/agent/appointment_decision_subgraph.py
    tests/unit/agent/test_appointment_decision_subgraph.py` -> All checks
    passed. `uv run mypy app/agent/appointment_decision_subgraph.py` ->
    Success.
  - Commit: `168048f` (`fix(agent): use the chat-bubble administracion title in the subgraph escalation`).

## Next step
T3: verification/regression tests for OPERATION_CREATE routing and free-text cancel/reschedule/book coverage.
