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
- [x] T3 Verify that `OPERATION_CREATE` sent from the fallback button opens the specialty list directly, and that free-text cancel / reschedule / book reach the appointment flow. Add regression tests; report any gap. Route: delegated (same writer).

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

- 2026-09-23 T3 (route: delegated, single writer):
  - T3(a) graph-level: added
    `test_operation_create_payload_from_the_fallback_button_opens_the_specialty_list`
    to `tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py`
    (highest-level seam already in the suite —
    `LangGraphAgentInvoker.handle()` against the real compiled graph):
    sends `OPERATION_CREATE_PAYLOAD` with no prior `collected_data["stage"]`
    (exactly the fallback's post-tap state) and asserts
    `messaging_gateway.sent_buttons == []` and
    `sent_lists[0][2].rows[0].title` contains the specialty name. Passed on
    first run — no production gap, `appointment.py`'s existing "no stage
    yet" -> `should_use_appointment_decision_subgraph` -> specialty list
    path already does this correctly.
  - T3(b) free-text cancel/reschedule/book: traced the real path —
    `resolve_interaction.py`'s `understand()` call ->
    `FakeLLMProvider.understand()`'s keyword layer (`app/infrastructure/llm/
    fake_llm_provider.py`) sets `operation_mention`, carried into
    `collected_data`, consumed by `appointment.py`'s "no stage yet" branch
    (`_OPERATION_BY_MENTION`). Found real **test gaps**, not code gaps: no
    test exercised the real (non-stubbed) `FakeLLMProvider.understand()`
    keyword layer for "cancelar"/"reagendar" phrasing, and no
    `appointment.py`-level test existed for a stated reschedule (only
    cancel and create had one). Closed them:
    - `tests/unit/infrastructure/llm/test_fake_llm_provider.py`:
      `test_understand_reads_a_cancel_request_as_cancel` ("quiero cancelar
      mi turno" -> "cancel") and
      `test_understand_reads_a_reschedule_request_as_reschedule" ("quiero
      reagendar" -> "reschedule"). ("quiero sacar un turno" -> "create"
      was already covered by
      `test_understand_still_reads_a_plain_booking_request_as_create`.)
    - `tests/unit/agent/nodes/test_resolve_interaction.py`:
      `test_free_text_operation_requests_reach_the_appointment_flow`,
      parametrized over the exact 3 phrases from the brief, using the real
      `FakeLLMProvider()` (not a stub) end to end through
      `create_resolve_interaction_node`.
    - `tests/unit/agent/nodes/test_appointment_node.py`:
      `test_a_stated_reschedule_skips_to_identification` (mirrors the
      existing cancel/create tests, closing the one operation missing
      appointment.py-level coverage).
    All new tests passed on first run — no code gap found, only closed
    test-coverage gaps. No new classifier was built.
  - `uv run pytest -q` -> 1562 passed, 82 skipped, 5 failed (exactly the 5
    known pre-existing failures: 4x
    `tests/unit/api/dependencies/test_gateway_dependency.py`, 1x
    `tests/integration/test_internal_eval_wiring.py`).
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy app` -> Success: no issues found in 320 source files.
  - Commit: pending (recorded after this write).

## Next step
None — T1-T3 complete, acceptance criteria met, working tree clean after the final commit.
