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
- Branch: `fix/fallback-menu-buttons` from `main`. PR #127 was squash-merged before these commits were pushed, so they were cherry-picked onto a fresh branch (original hashes on `fix/slot-list-duplicate-row-ids`: b39876d, 168048f, fd7ce2c, f455447).

## Tasks
- [x] T1 Fallback buttons become `📅 Agendar una cita` (`OPERATION_CREATE`) and `💬 Administración` (`MENU_ADMIN`). Update the fallback LLM context (`opciones_del_menu`) and the reply so a confused patient is asked whether they want to talk to administration. Route: delegated.
- [x] T2 The subgraph escalation button "Administración" becomes `💬 Administración`. Route: delegated (same writer).
- [x] T3 Verify that `OPERATION_CREATE` sent from the fallback button opens the specialty list directly, and that free-text cancel / reschedule / book reach the appointment flow. Add regression tests; report any gap. Route: delegated (same writer).
- [x] T4 Fix the review findings. (a) WARNING: tapping `📅 Agendar una cita` (`OPERATION_CREATE`) after a fallback that kept a stale stage (e.g. `awaiting_slot_selection` or `awaiting_identification`) must still open the specialty list; prove it with an invoker-level test and fix the routing if needed. (b) SUGGESTION: also assert the slot title's UTF-16 length is at most 20. Route: delegated.

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
  - Commit: `ac92e95` (`fix(agent): swap fallback buttons for book+administracion actions`).

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
  - Commit: `1ccd448` (`fix(agent): use the chat-bubble administracion title in the subgraph escalation`).

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
  - Commit: `2cc028f` (`test(agent): cover OPERATION_CREATE-from-fallback and free-text operation routing`).

- 2026-09-23 T4 (route: delegated, single writer, strict TDD; native review findings on this branch):
  - **Traced the premise first**: read `resolve_interaction.py` end to end —
    intent="unknown" (the only route to `FALLBACK_NODE`) is only ever
    returned when `has_active_stage` is False; every button/free-text
    branch while a stage IS active returns `intent="appointment"` (or an
    information/handoff intent) instead. So `fallback.py` never actually
    runs with `collected_data["stage"]` still set in the live routing —
    the WARNING's literal premise ("the patient taps the fallback's
    button while a stage lingers") can't occur through normal routing.
    Tested the more general, real-world-equivalent risk instead: whatever
    got a stale stage onto the checkpointer (a bug, a race, a future
    routing change), does `OPERATION_CREATE_PAYLOAD` still safely reset
    it? That's exactly what `appointment.py`'s existing `_MAIN_MENU_PAYLOADS`
    reset (already added for an earlier, similar live bug — see its own
    comment at line ~432) is supposed to guarantee.
  - (a) RED/GREEN, routing: added
    `test_operation_create_from_a_lingering_stage_still_opens_the_specialty_list`
    to `tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py`
    (same `LangGraphAgentInvoker.handle()` seam as T3(a)), parametrized
    over 3 lingering stages seeded directly on the checkpointer via
    `compiled_graph.aupdate_state(...)`: `awaiting_slot_selection`
    (subgraph-owned), `awaiting_identification` (legacy-owned,
    reschedule), `awaiting_appointment_selection` (cancel). All 3 passed
    on first run — **routing did not need a fix**: `_MAIN_MENU_PAYLOADS`
    already resets `stage`/`collected_data` before any stage-conditional
    branch, for every stage (legacy or subgraph-delegated), since
    `create_appointment_node` is the single node used for all of them.
  - (a) RED/GREEN, pending action: also added
    `test_operation_create_from_a_lingering_confirmation_drops_the_stale_pending_action`
    seeding `stage=awaiting_confirmation` + `pending_action_id=
    "stale-pending-action"`, then tapping `OPERATION_CREATE_PAYLOAD`. RED:
    `uv run pytest -q ... -k lingering` failed 1/4
    (`assert 'stale-pending-action' is None`) — the stale
    `pending_action_id` DID survive into the new specialty-selection
    flow's checkpointed state, because neither `_offer_specialties` nor
    `_delegate_to_decision_subgraph` return/change that field on their
    own. GREEN: `app/agent/nodes/appointment.py`'s `CREATE_APPOINTMENT_ACTION`
    branch (~line 3510) now explicitly merges `"pending_action_id": None`
    into its result whenever `returned_to_main_menu` is true — mirrors
    `MENU_MAIN_PAYLOAD`'s own explicit reset a few lines above, reusing
    that existing pattern rather than new logic. `uv run pytest -q
    tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py -k
    lingering` -> 4 passed. `uv run pytest -q
    tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py
    tests/unit/agent` -> 347 passed (no regressions).
    Harm assessment: a lingering `pending_action_id` is only ever read at
    `STAGE_AWAITING_CONFIRMATION`; since `stage` is reset away from it in
    the same turn, the stale id was never actually reachable before this
    fix either — the fix is defense-in-depth/hygiene (matching
    `MENU_MAIN_PAYLOAD`'s own existing convention), not a fix for an
    exploitable bug.
  - (b) `tests/unit/agent/nodes/test_appointment_selection.py`'s
    `test_slot_rows_titles_never_exceed_twenty_characters`: added
    `assert len(row.title.encode("utf-16-le")) // 2 <= 20` alongside the
    existing codepoint-`len()` check. Passed immediately for all 7
    weekday variants — no title exceeds 20 UTF-16 units either (the 🕐
    clock emoji is a surrogate pair, e.g. `len()==17` vs UTF-16-units==18
    for one sample title, both still under the 20 cap). No gap found; no
    format change made.
  - `uv run pytest -q` -> 1566 passed, 82 skipped, 5 failed (exactly the 5
    known pre-existing failures).
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy app` -> Success: no issues found in 320 source files.
  - Commit: `4673f20` (`fix(agent): drop a stale pending action when OPERATION_CREATE resets a lingering stage`).

## Next step
None — T1-T4 complete, acceptance criteria met, working tree clean after the final commit.
