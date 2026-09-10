# Tasks: migrate-appointment-decision-subgraph

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900-1,300 across three PRs; target 250-400 per PR |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 pure helper/compatibility extraction → PR 2 typed create-selection subgraph and adapter → PR 3 checkpoint/interruption/browse separation/observability hardening |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

## Chain Plan

```text
main
  PR 1: helper extraction and compatibility map 📍
    PR 2: typed create-selection subgraph behind appointment contract
      PR 3: checkpoint/interruption/browse separation/observability hardening
```

Global constraints:

- Keep `app/agent/graph.py` top-level `APPOINTMENT_NODE = "appointment"` route contract stable.
- Keep `AgentState.collected_data["stage"]` as the public checkpoint cursor; do not persist internal decision node names.
- Do not introduce new checkpointed dataclasses/enums for this slice.
- Do not migrate identification, verification, registration, confirmation, no-slot/no-availability follow-up handlers, pending-action confirmation, or Dentalink writes.
- Use strict TDD in each PR: RED tests before production edits, then GREEN, TRIANGULATE, REFACTOR.

## PR 1 — Pure helper/compatibility extraction with no behavior change

Dependency: starts from `main` with current legacy appointment FSM intact.

Allowed edit surfaces:

- `app/agent/nodes/appointment.py`
- `app/agent/nodes/appointment_selection.py` (new)
- `tests/unit/agent/nodes/test_appointment_node.py`
- `tests/unit/agent/nodes/test_appointment_list_pagination.py`
- Optional pure helper tests in `tests/unit/agent/nodes/test_appointment_selection.py` (new)

Rollback point: revert PR 1 to restore all helper logic directly inside `app/agent/nodes/appointment.py`; no runtime toggle or data cleanup required.

Focused verification commands:

```bash
uv run ruff check app/agent/nodes/appointment.py app/agent/nodes/appointment_selection.py tests/unit/agent/nodes/test_appointment_node.py tests/unit/agent/nodes/test_appointment_list_pagination.py tests/unit/agent/nodes/test_appointment_selection.py
uv run mypy app/
uv run pytest tests/unit/agent/nodes/test_appointment_node.py tests/unit/agent/nodes/test_appointment_list_pagination.py tests/unit/agent/nodes/test_appointment_selection.py
```

### RED

- [x] Add characterization tests in `tests/unit/agent/nodes/test_appointment_selection.py` for `LEGACY_STAGE_TO_DECISION_NODE`, legacy-stage-to-entry-node mapping, and non-migrated no-availability/no-slot stages before creating the helper module. <!-- sdd-owner: implementation -->
- [x] Add or tighten characterization tests in `tests/unit/agent/nodes/test_appointment_node.py` proving current create-selection behavior for `SPECIALTY:`, `PROFESSIONAL:`, `LIST_MORE`, `LIST_BACK`, invalid payloads, and stale slot payloads remains unchanged. <!-- sdd-owner: implementation -->
- [x] Run `uv run pytest tests/unit/agent/nodes/test_appointment_node.py tests/unit/agent/nodes/test_appointment_list_pagination.py tests/unit/agent/nodes/test_appointment_selection.py` and record the expected RED failures for missing extracted symbols only. <!-- sdd-owner: implementation -->

### GREEN

- [x] Create `app/agent/nodes/appointment_selection.py` and move only pure constants/helpers from `app/agent/nodes/appointment.py`, including `SELECT_SLOT_PAYLOAD_PREFIX`, stage/node compatibility mapping, payload resolution helpers, pagination helpers, and reusable list/button builders where extraction does not change copy or payloads. <!-- sdd-owner: implementation -->
- [x] Update `app/agent/nodes/appointment.py` imports and call sites to use `app/agent/nodes/appointment_selection.py` while preserving legacy branch order, side effects, response text, payload IDs, and input-state calls. <!-- sdd-owner: implementation -->
- [x] Keep `STAGE_AWAITING_SPECIALTY_SELECTION`, `STAGE_AWAITING_PROFESSIONAL_SELECTION`, `STAGE_AWAITING_SLOT_SELECTION`, `STAGE_AWAITING_NO_AVAILABILITY_CHOICE`, and `STAGE_AWAITING_NO_SLOTS_CHOICE` readable from the legacy appointment module or through compatible imports used by existing tests. <!-- sdd-owner: implementation -->
- [x] Run the focused PR 1 pytest command and confirm all PR 1 tests pass without changing user-visible behavior. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [x] Add cases in `tests/unit/agent/nodes/test_appointment_selection.py` for changed specialty invalidating professional/slot data and changed professional invalidating slot data through `app/agent/workflow_state.py::invalidate_from` helper usage. <!-- sdd-owner: implementation -->
- [x] Add cases in `tests/unit/agent/nodes/test_appointment_selection.py` that `awaiting_no_availability_choice` and `awaiting_no_slots_choice` are not mapped to migrated decision entry nodes. <!-- sdd-owner: implementation -->
- [x] Run `uv run pytest tests/unit/agent/nodes/test_appointment_selection.py tests/unit/agent/nodes/test_appointment_node.py` and confirm extraction remains behavior-neutral. <!-- sdd-owner: implementation -->

### REFACTOR

- [x] Remove duplicate helper logic left in `app/agent/nodes/appointment.py` only after tests prove identical behavior through `app/agent/nodes/appointment_selection.py`. <!-- sdd-owner: implementation -->
- [x] Run `uv run ruff check .`, `uv run mypy app/`, and the focused PR 1 pytest command before opening PR 1. <!-- sdd-owner: implementation -->

## PR 2 — Typed create-selection subgraph and adapter

Dependency: stacks on PR 1; helper extraction and compatibility mapping are available.

Allowed edit surfaces:

- `app/agent/appointment_decision_subgraph.py` (new)
- `app/agent/nodes/appointment.py`
- `app/agent/nodes/appointment_selection.py`
- `tests/unit/agent/test_appointment_decision_subgraph.py` (new)
- `tests/unit/agent/nodes/test_appointment_node.py`
- Optional fixture-only changes under `tests/unit/agent/` needed by the new subgraph tests

Rollback point: disable/remove `should_use_appointment_decision_subgraph(...)` delegation in `app/agent/nodes/appointment.py`; leave PR 1 helpers in place and fall back to the legacy FSM.

Focused verification commands:

```bash
uv run ruff check app/agent/appointment_decision_subgraph.py app/agent/nodes/appointment.py app/agent/nodes/appointment_selection.py tests/unit/agent/test_appointment_decision_subgraph.py tests/unit/agent/nodes/test_appointment_node.py
uv run mypy app/
uv run pytest tests/unit/agent/test_appointment_decision_subgraph.py tests/unit/agent/nodes/test_appointment_node.py tests/unit/agent/nodes/test_appointment_list_pagination.py
```

### RED

- [x] Add direct subgraph tests in `tests/unit/agent/test_appointment_decision_subgraph.py` for route entry from `awaiting_specialty_selection`, `awaiting_professional_selection`, `awaiting_slot_selection`, and no stage with create-booking context. <!-- sdd-owner: implementation -->
- [x] Add direct subgraph tests in `tests/unit/agent/test_appointment_decision_subgraph.py` for valid/invalid/stale `SPECIALTY:`, `PROFESSIONAL:`, and `SELECT_SLOT:` payload handling against current checkpointed options. <!-- sdd-owner: implementation -->
- [x] Add direct subgraph tests in `tests/unit/agent/test_appointment_decision_subgraph.py` for availability-with-slots, no-availability legacy exit, and pre-identification slot selection storing `pending_selected_slot` without pending-action creation. <!-- sdd-owner: implementation -->
- [x] Run `uv run pytest tests/unit/agent/test_appointment_decision_subgraph.py` and record RED failures for missing `app/agent/appointment_decision_subgraph.py` graph, state, and adapter symbols. <!-- sdd-owner: implementation -->

### GREEN

- [x] Create `app/agent/appointment_decision_subgraph.py` with `AppointmentDecisionState` as a narrow `TypedDict`, primitive result fields, graph construction using conditional edges, and no reducers or checkpointed custom state. <!-- sdd-owner: implementation -->
- [x] Implement `route_entry`, `choose_specialty`, `choose_professional`, `search_availability`, and `choose_slot` node functions in `app/agent/appointment_decision_subgraph.py`, returning partial state updates only and not mutating incoming state. <!-- sdd-owner: implementation -->
- [x] Ensure `search_availability` uses the existing 14-day window, option limit, `SearchAvailabilityUseCase`, and `professional_id`, while deliberately passing `specialty_id=None`. <!-- sdd-owner: implementation -->
- [x] Ensure `choose_slot` accepts only `SELECT_SLOT:<id>` for current `available_slots`, stores `pending_selected_slot` for create-before-identity, and never constructs/calls pending-action or Dentalink write use cases. <!-- sdd-owner: implementation -->
- [x] Add `should_use_appointment_decision_subgraph(...)` and adapter invocation inside `create_appointment_node(...)` in `app/agent/nodes/appointment.py` for only first-slice create stages and contexts. <!-- sdd-owner: implementation -->
- [x] Convert subgraph results into partial `AgentState` updates in `app/agent/nodes/appointment.py`, calling legacy `_begin_identification(...)` only when `exit_reason == "begin_identification"`. <!-- sdd-owner: implementation -->
- [x] Run the focused PR 2 pytest command and confirm the subgraph path passes while existing appointment-node tests remain green. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [x] Add integration-style unit cases in `tests/unit/agent/nodes/test_appointment_node.py` proving the top-level appointment node delegates migrated create-selection stages while no-availability/no-slot follow-up stages remain legacy-owned. <!-- sdd-owner: implementation -->
- [x] Add tests in `tests/unit/agent/test_appointment_decision_subgraph.py` proving internal `decision_node` attribution never replaces `collected_data["stage"]`. <!-- sdd-owner: implementation -->
- [x] Add tests in `tests/unit/agent/test_appointment_decision_subgraph.py` proving reschedule/cancel markers produce `exit_reason="not_migrated"` or equivalent legacy fallback rather than create-selection handling. <!-- sdd-owner: implementation -->
- [x] Run `uv run pytest tests/unit/agent/test_appointment_decision_subgraph.py tests/unit/agent/nodes/test_appointment_node.py tests/unit/agent/nodes/test_appointment_list_pagination.py` after triangulation. <!-- sdd-owner: implementation -->

### REFACTOR

- [x] Review `app/agent/appointment_decision_subgraph.py` for LangGraph correctness: compiled graph, no `Command(goto=...)`, no mixed static edges with dynamic goto, and valid conditional destinations. <!-- sdd-owner: implementation -->
- [x] Remove temporary duplication between `app/agent/nodes/appointment.py` and `app/agent/appointment_decision_subgraph.py` only when the helper module owns the shared behavior and tests still pass. <!-- sdd-owner: implementation -->
- [x] Run `uv run ruff check .`, `uv run mypy app/`, and the focused PR 2 pytest command before opening PR 2. <!-- sdd-owner: implementation -->

## PR 3 — Checkpoint/interruption/browse separation/observability hardening

Dependency: stacks on PR 2; create-selection subgraph is delegated behind the stable appointment route.

Allowed edit surfaces:

- `app/agent/appointment_decision_subgraph.py`
- `app/agent/nodes/appointment.py`
- `app/agent/nodes/appointment_selection.py`
- `app/agent/nodes/specialties.py`
- `app/agent/nodes/resolve_interaction.py` only if tests prove a regression in existing interruption metadata
- `app/infrastructure/agent/langgraph_agent_invoker.py` only if tests prove carry-over regression
- `tests/unit/agent/test_appointment_decision_subgraph.py`
- `tests/unit/agent/test_checkpoint_list_allowlist.py`
- `tests/unit/agent/nodes/test_resolve_interaction_v2.py`
- `tests/unit/agent/nodes/test_specialties_node.py`
- `tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py`
- Existing appointment safety/eval tests when present under `tests/unit/agent/` or `tests/agent/`

Rollback point: revert PR 3 hardening changes independently; browse-vs-booking separation can be reverted without removing PR 2 delegation, and observability can be removed without checkpoint data migration.

Focused verification commands:

```bash
uv run ruff check app/agent/appointment_decision_subgraph.py app/agent/nodes/appointment.py app/agent/nodes/specialties.py app/agent/nodes/resolve_interaction.py app/infrastructure/agent/langgraph_agent_invoker.py tests/unit/agent/test_checkpoint_list_allowlist.py tests/unit/agent/nodes/test_resolve_interaction_v2.py tests/unit/agent/nodes/test_specialties_node.py tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py
uv run mypy app/
uv run pytest tests/unit/agent/test_appointment_decision_subgraph.py tests/unit/agent/test_checkpoint_list_allowlist.py tests/unit/agent/nodes/test_resolve_interaction_v2.py tests/unit/agent/nodes/test_specialties_node.py tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py
uv run pytest
```

### RED

- [ ] Add old-checkpoint compatibility tests in `tests/unit/agent/test_checkpoint_list_allowlist.py` for `awaiting_specialty_selection`, `awaiting_professional_selection`, and `awaiting_slot_selection` checkpoints without new persisted subgraph state. <!-- sdd-owner: implementation -->
- [ ] Add multi-turn checkpointer-thread tests in `tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py` proving `collected_data`, `pending_selected_slot`, `appointment_action`, `missing_fields`, and `pending_action_id` carry over across the migrated path. <!-- sdd-owner: implementation -->
- [ ] Add interruption/resume tests in `tests/unit/agent/nodes/test_resolve_interaction_v2.py` for location interruption from `awaiting_professional_selection` and question interruption from `awaiting_slot_selection`. <!-- sdd-owner: implementation -->
- [ ] Add browse-vs-booking separation tests in `tests/unit/agent/nodes/test_specialties_node.py` proving catalog browsing does not set `operation=create_appointment`, `awaiting_specialty_selection`, `awaiting_professional_selection`, `chosen_specialty_id`, or `chosen_professional_id` without booking context. <!-- sdd-owner: implementation -->
- [ ] Add safety tests in `tests/unit/agent/test_appointment_decision_subgraph.py` or `tests/unit/agent/nodes/test_appointment_node.py` proving no Dentalink create/reschedule/cancel write and no `ProposeAppointmentUseCase` call occurs before identity and explicit confirmation. <!-- sdd-owner: implementation -->
- [ ] Run the focused PR 3 pytest command and record RED failures for missing hardening or browse-separation behavior. <!-- sdd-owner: implementation -->

### GREEN

- [ ] Harden `app/agent/appointment_decision_subgraph.py` route-entry logic so legacy no-availability/no-slot, identification, verification, registration, confirmation, reschedule, and cancel states fall through to legacy ownership. <!-- sdd-owner: implementation -->
- [ ] Adjust `app/agent/nodes/specialties.py` so read-only specialty browsing remains catalog-only unless `MENU_APPOINTMENT_PAYLOAD`, `OPERATION_CREATE_PAYLOAD`, active appointment cursor, `operation_mention="create"`, or explicit booking context is present. <!-- sdd-owner: implementation -->
- [ ] Preserve or minimally repair `app/agent/nodes/resolve_interaction.py` temporary interruption metadata so `active_node` and `resume_node` keep legacy stage strings across location/question detours. <!-- sdd-owner: implementation -->
- [ ] Preserve or minimally repair `app/infrastructure/agent/langgraph_agent_invoker.py` checkpoint carry-over for `appointment_action`, `collected_data`, `missing_fields`, and `pending_action_id`. <!-- sdd-owner: implementation -->
- [ ] Add structured internal decision logging in `app/agent/appointment_decision_subgraph.py` with `conversation_id`, legacy `stage`, `decision_node`, and `exit_reason`, without writing internal node names into public stage fields. <!-- sdd-owner: implementation -->
- [ ] Run the focused PR 3 pytest command and confirm hardening tests pass. <!-- sdd-owner: implementation -->

### TRIANGULATE

- [ ] Add tests in `tests/unit/agent/test_appointment_decision_subgraph.py` asserting returned diagnostic metadata identifies `choose_specialty`, `choose_professional`, `search_availability`, and `choose_slot` while preserving legacy stage strings. <!-- sdd-owner: implementation -->
- [ ] Add tests in `tests/unit/agent/nodes/test_specialties_node.py` proving explicit booking context still enters booking selection and valid specialty selection advances to professional selection. <!-- sdd-owner: implementation -->
- [ ] Add or run existing appointment safety/eval scenarios for no invented availability, no stale confirmation, and no sensitive execution before confirmation, using their repository paths discovered under `tests/`. <!-- sdd-owner: implementation -->
- [ ] Run `uv run pytest tests/unit/agent/test_appointment_decision_subgraph.py tests/unit/agent/nodes/test_specialties_node.py tests/unit/agent/nodes/test_resolve_interaction_v2.py tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py`. <!-- sdd-owner: implementation -->

### REFACTOR

- [ ] Confirm `app/agent/state.py` and checkpoint serializer allowlists remain unchanged; if a test forces allowlist changes, document why in `tests/unit/agent/test_checkpoint_list_allowlist.py` and keep persisted types existing/allowlisted only. <!-- sdd-owner: implementation -->
- [ ] Review PR 3 diff for review budget; if the cohesive hardening slice exceeds 400 changed lines after one honest slicing pass, report the overage and request `size:exception` rather than compressing code or deleting tests. <!-- sdd-owner: implementation -->
- [ ] Run final chain verification: `uv run ruff check .`, `uv run mypy app/`, and `uv run pytest` before opening PR 3. <!-- sdd-owner: implementation -->
