```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:1b75b951d1f4e4adc157077b2a00f9ef4c41c9344d00e0fb734e405db8668264
verdict: pass
blockers: 0
critical_findings: 0
requirements: 9/9
scenarios: 20/20
test_command: uv run pytest tests/unit -q
test_exit_code: 0
test_output_hash: sha256:1b2750b32cfa218b5f78c47c51e410d7c3c6166aecbe7954c39aaed84543106c
build_command: uv run mypy app/
build_exit_code: 0
build_output_hash: sha256:67a78fbc64b18daac90bc25a747d847b916095e566d28a893061088f62fa9ac8
```

## Verification Report

**Change**: migrate-appointment-decision-subgraph
**Version**: N/A (no versioned spec header)
**Mode**: Strict TDD
**Scope of this pass**: PR 3 only (checkpoint/interruption/browse-separation/observability hardening), stacked on merged PR1+PR2. PR1/PR2 internals not re-verified; end-to-end coherence sanity-checked across all three.

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total (PR3) | 19 |
| Tasks complete (PR3) | 19 |
| Tasks incomplete (PR3) | 0 |
| Tasks total (whole change, PR1+PR2+PR3) | 58 |
| Tasks complete (whole change) | 58 |

All 19 PR3 checkboxes in `tasks.md` are `[x]`, each backed by real code/test evidence traced below (not blanket-checked).

### Build & Tests Execution
**Build**: ✅ Passed
```text
$ uv run ruff check app/agent/appointment_decision_subgraph.py app/agent/nodes/appointment.py app/agent/nodes/specialties.py app/agent/nodes/resolve_interaction.py app/infrastructure/agent/langgraph_agent_invoker.py tests/unit/agent/test_checkpoint_list_allowlist.py tests/unit/agent/nodes/test_resolve_interaction_v2.py tests/unit/agent/nodes/test_specialties_node.py tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py
All checks passed!

$ uv run ruff check .
All checks passed!

$ uv run mypy app/
Success: no issues found in 294 source files
```

**Tests**: ✅ 80 passed (focused PR3 slice) / ✅ 1323 passed (full `tests/unit`), 0 failed
```text
$ uv run pytest tests/unit/agent/test_appointment_decision_subgraph.py tests/unit/agent/test_checkpoint_list_allowlist.py tests/unit/agent/nodes/test_resolve_interaction_v2.py tests/unit/agent/nodes/test_specialties_node.py tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py tests/unit/agent/nodes/test_specialties_list_pagination.py -q
80 passed in 1.67s

$ uv run pytest tests/unit -q
1323 passed, 2 warnings in 9.67s
```
(`tests/integration/` not run — requires live DB/Redis, unavailable in this sandbox, consistent with apply-progress's own report; out of scope for unit-level SDD verification.)

**Coverage**: not measured — no coverage tool invoked in this pass (ruff/mypy/pytest only, per task's specified commands).

### Spec Compliance Matrix
(Spec covers the full change; PR-ownership noted per requirement — PR3 requirements verified by fresh evidence this pass, PR1/PR2-owned requirements re-confirmed only via the green full suite, not re-audited line-by-line.)

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Legacy Checkpoint Stage Compatibility | Resume from specialty selection checkpoint | `test_checkpoint_list_allowlist.py::test_old_specialty_selection_checkpoint_resumes_without_new_persisted_state` | ✅ COMPLIANT (PR3) |
| Legacy Checkpoint Stage Compatibility | Resume from professional selection checkpoint | `test_checkpoint_list_allowlist.py::test_old_professional_selection_checkpoint_resumes_without_new_persisted_state` | ✅ COMPLIANT (PR3) |
| Legacy Checkpoint Stage Compatibility | Resume from slot selection checkpoint | `test_checkpoint_list_allowlist.py::test_old_slot_selection_checkpoint_resumes_without_new_persisted_state` | ✅ COMPLIANT (PR3) |
| Typed Create-Selection Subgraph Boundary | No top-level route change | `test_appointment_decision_subgraph.py` (PR2 suite) | ✅ COMPLIANT (PR2, re-confirmed green) |
| Typed Create-Selection Subgraph Boundary | Narrow state projection | `test_appointment_decision_subgraph.py` (PR2 suite) | ✅ COMPLIANT (PR2, re-confirmed green) |
| Specialty Browse and Booking Separation | Browse specialty without booking context | `test_specialties_node.py`, `test_specialties_list_pagination.py::test_specialty_row_tap_from_the_catalog_stays_read_only_without_booking_context`, `::test_professional_listing_from_the_catalog_stays_read_only_without_booking_context` | ✅ COMPLIANT (PR3) |
| Specialty Browse and Booking Separation | Booking specialty selection with booking context | `test_specialties_list_pagination.py::test_specialty_row_tap_with_booking_context_opens_its_professionals`, `::test_professional_listing_from_the_catalog_with_booking_context_is_a_paginated_list`, `test_specialties_node.py` booking-context cases | ✅ COMPLIANT (PR3, regression-safe) |
| Temporary Interruption Resume Compatibility | Location interruption resumes selection | `test_resolve_interaction_v2.py::test_location_interruption_from_professional_selection_resumes_the_same_cursor` | ✅ COMPLIANT (PR3) |
| Temporary Interruption Resume Compatibility | Question interruption resumes slot choice | `test_resolve_interaction_v2.py::test_question_interruption_from_slot_selection_preserves_the_slot_cursor` | ✅ COMPLIANT (PR3) |
| Selection Dependency Invalidation | Specialty change clears downstream selections | `test_appointment_selection.py` (PR1 suite) | ✅ COMPLIANT (PR1, re-confirmed green) |
| Selection Dependency Invalidation | Professional change clears slot data | `test_appointment_selection.py` (PR1 suite) | ✅ COMPLIANT (PR1, re-confirmed green) |
| No Premature PendingAction or Dentalink Writes | Slot selected before identification | `test_appointment_decision_subgraph.py` (PR2 suite: `pending_selected_slot` without pending-action) | ✅ COMPLIANT (PR2, re-confirmed green) |
| No Premature PendingAction or Dentalink Writes | Availability search is read-only | `test_appointment_decision_subgraph.py::test_subgraph_module_never_imports_sensitive_write_use_cases` (PR3, new structural guarantee) | ✅ COMPLIANT (PR3, strengthened) |
| No-Slot Handoff to Legacy Behavior | No availability returned | `test_appointment_decision_subgraph.py` (PR2 suite) | ✅ COMPLIANT (PR2, re-confirmed green) |
| No-Slot Handoff to Legacy Behavior | No-availability follow-up remains legacy-owned | `test_appointment_decision_subgraph.py::test_route_entry_rejects_no_availability_choice_stage`, `::test_route_entry_rejects_no_slots_choice_stage` (PR3 regression tests) | ✅ COMPLIANT (PR3) |
| Deterministic Payload Handling | Valid payload resolves exactly once | `test_appointment_decision_subgraph.py` (PR2 suite) | ✅ COMPLIANT (PR2, re-confirmed green) |
| Deterministic Payload Handling | Stale payload is rejected | `test_appointment_decision_subgraph.py` (PR2 suite) | ✅ COMPLIANT (PR2, re-confirmed green) |
| Deterministic Payload Handling | Pagination payload preserves cursor | `test_specialties_list_pagination.py` (PR3-updated, still asserts `LIST_MORE_PAYLOAD` cursor + same-stage behavior) | ✅ COMPLIANT (PR3) |
| Observability Without Public Behavior Drift | Internal node attribution is available | `test_appointment_decision_subgraph.py::test_choose_specialty_decision_node_is_attributed_when_offering_specialties` (+3 siblings, PR3) | ✅ COMPLIANT (PR3) |
| Observability Without Public Behavior Drift | Legacy payload formats remain stable | Full suite green incl. `test_specialties_node.py`, `test_appointment_node.py` payload-prefix assertions | ✅ COMPLIANT (PR2/PR3, re-confirmed green) |

**Compliance summary**: 20/20 scenarios compliant.

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| `_has_booking_context(...)` gate correctness | ✅ Implemented | Read directly in `app/agent/nodes/specialties.py:36-70`. Gates on `MENU_APPOINTMENT_PAYLOAD`/`OPERATION_CREATE_PAYLOAD` button, `collected_data["operation"]==CREATE_APPOINTMENT_ACTION`, `collected_data["operation_mention"]=="create"`, or `collected_data["stage"] is not None`. Applied identically at both the named-professional-match branch (line 155) and the row-tap/named-specialty branch (line 216); browse-only returns never include `stage`/`operation`/`chosen_specialty_id`/`chosen_professional_id` in `collected_data`. |
| Observability logging isolation | ✅ Implemented | `_traced(...)` wrapper in `app/agent/appointment_decision_subgraph.py:189-224` only calls `logger.info(...)` with `decision_node`/`exit_reason`/legacy `stage`; it returns `result` unchanged. `decision_node`/`exit_reason` are top-level `AppointmentDecisionState` fields (never nested inside `collected_data`), and the adapter (`appointment.py::_delegate_to_decision_subgraph`, lines 991-1042) builds `updates` from an explicit key whitelist (`response_text`, `response_buttons`, `requires_handoff`, `response_list`, `response_flow`, `collected_data`, `pending_action_id`) that never copies `decision_node`/`exit_reason` into `AgentState`. No leak into checkpointed state. |
| Checkpoint allowlist unchanged | ✅ Implemented | `git diff --stat refactor/appointment-decision-subgraph-pr2 -- app/agent/state.py` is empty — confirmed no allowlist/serializer change. |
| `resolve_interaction.py` needed no changes | ✅ Implemented | `git diff --stat refactor/appointment-decision-subgraph-pr2 -- app/agent/nodes/resolve_interaction.py` is empty — 2 new regression tests in `test_resolve_interaction_v2.py` pass against the unmodified file, confirming the apply report's claim. |
| `langgraph_agent_invoker.py` needed no changes | ✅ Implemented | `git diff --stat refactor/appointment-decision-subgraph-pr2 -- app/infrastructure/agent/langgraph_agent_invoker.py` is empty — new 6-turn checkpointer carry-over tests pass against the unmodified file. |
| No premature Dentalink writes across PR1+PR2+PR3 | ✅ Implemented | Traced directly: `ProposeAppointmentUseCase`/`ConfirmPendingActionUseCase` are only constructed/called inside `app/agent/nodes/appointment.py::create_appointment_node`, gated behind `awaiting_slot_selection`/`awaiting_confirmation` stages that are only reachable after `awaiting_identification` resolves the patient (pre-existing PR1/PR2 FSM, untouched by PR3 — `appointment.py` has zero diff vs the PR2 base). `appointment_decision_subgraph.py` never imports these symbols at all, now backed by a structural test (`forbidden_symbols.isdisjoint(vars(subgraph_module))`). |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Internal decision-node names never replace public `collected_data["stage"]` | ✅ Yes | Confirmed via code trace above and passing `test_choose_*_decision_node_is_attributed_*` tests. |
| `app/agent/state.py` and checkpoint serializer allowlists stay unchanged | ✅ Yes | Empty diff confirmed directly. |
| Browse-vs-booking separation implemented as a minimal, explicit gate | ✅ Yes | `_has_booking_context(...)` is a small pure function with a documented rationale; no broader refactor. |
| PR3 hardening independently revertible without undoing PR2 delegation | ✅ Yes | Route-entry hardening was already correct from PR1/PR2's `LEGACY_STAGE_TO_DECISION_NODE` mapping; PR3's only production changes are additive (`_has_booking_context` gate, `_traced` wrapper) — both removable independently. |

### Issues Found

**CRITICAL**: None

**WARNING**: None

**SUGGESTION**:
1. `Deterministic Payload Handling > Pagination payload preserves cursor` and several PR1/PR2-owned scenarios above are marked compliant on the strength of the green full suite, not a fresh line-by-line re-audit — acceptable per this task's explicit "don't re-verify PR1/PR2 internals" scope, noted here only for traceability.
2. The 400-line PR3 review-budget overage (718 changed lines per apply-progress, ~685/33 per direct diff-stat) still needs the maintainer's `size:exception` grant before merge — this is a process/delivery gate, not a code defect, and matches the same precedented pattern already used for PR1 and PR2.

### Edit-Surface Deviation Verdict (`tests/unit/agent/nodes/test_specialties_list_pagination.py`)

**Verdict: legitimate, minimal, safety-preserving collateral fix — not scope creep.**

Evidence:
- The file was NOT in PR3's literal `Allowed edit surfaces` list (which only catch-alls "Existing appointment safety/eval tests... under `tests/unit/agent/` or `tests/agent/`" — a pagination test is not a safety/eval test, so this genuinely falls outside the literal list).
- The trigger was a mandatory, spec-required production change: `_has_booking_context(...)` in `specialties.py` (itself explicitly in-surface) correctly stopped 2 pre-existing tests in this file from passing, because those tests asserted the OLD, spec-violating "any catalog match always enters booking" behavior.
- The diff (read directly, see command trail above) does not weaken or gut any assertion. It:
  - Renames the 2 broken tests to `..._stays_read_only_without_booking_context` and changes their assertions from `stage == awaiting_professional_selection` to `"stage" not in collected_data` (and, for the row-tap case, also `"chosen_specialty_id" not in collected_data`) plus a `response_list is not None` check — a real, meaningful behavioral assertion for the new spec requirement, not a deletion.
  - Adds 2 new companion tests (`..._with_booking_context_...`) that assert the OLD behavior (`stage == awaiting_professional_selection`, correct pagination `LIST_MORE_PAYLOAD` cursor) still holds when `operation_mention: "create"` context is present — proving no regression for real booking flows.
  - The pagination-specific assertion (`ids[-1] == LIST_MORE_PAYLOAD`) is preserved unchanged in both the browse-only and booking-context variants — pagination behavior itself was never touched, only the stage-writing side effect.
- This exactly mirrors the pattern already used (and pre-approved) in the officially in-surface `test_specialties_node.py`, so it is consistent with, not divergent from, the sanctioned fix shape.
- Net effect: 2 tests updated (not deleted), 2 tests added — strictly additive test coverage, and it is the reason the full suite is green rather than red. Declining to make this fix would have left 2 failing tests asserting behavior the spec explicitly overturns, which is a worse outcome than the honest, disclosed deviation the apply agent chose and self-reported.

### TDD Compliance
| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | apply-progress observation #671 documents RED/GREEN/TRIANGULATE/REFACTOR work and a real pre-existing-test break discovered mid-implementation, handled honestly. |
| All tasks have tests | ✅ | 19/19 PR3 tasks.md checkboxes map to real test files verified above. |
| RED confirmed (tests exist) | ✅ | All named test files exist and contain the described test functions (confirmed via `git diff`). |
| GREEN confirmed (tests pass) | ✅ | 80/80 focused PR3 tests pass; 1323/1323 `tests/unit` pass on fresh execution this pass. |
| Triangulation adequate | ✅ | Browse-vs-booking separation triangulated with both browse-only and booking-context variants in 2 files; checkpoint compatibility triangulated across 3 stages + a parametrized 6-case non-migrated-stage test. |
| Safety Net for modified files | ✅ | `specialties.py` modification is covered by both the updated collateral tests and the officially in-surface `test_specialties_node.py`; `resolve_interaction.py`/`langgraph_agent_invoker.py` had pre-existing suites plus new regression tests run before/after confirming no behavior change (0-line diff). |

**TDD Compliance**: 6/6 checks passed

---

### Test Layer Distribution
| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 80 (PR3 focused) / 1323 (full `tests/unit`) | 6 PR3-touched test files | pytest, pytest-asyncio |
| Integration | not run | — | requires live DB/Redis, unavailable in this sandbox |
| E2E | 0 | — | not applicable to this change |
| **Total** | **1323** | | |

---

### Changed File Coverage
Coverage analysis skipped — no coverage tool invoked in this pass (task specified ruff/mypy/pytest commands only).

---

### Assertion Quality
✅ All assertions verify real behavior — no tautologies, ghost loops, orphan empty-checks without companion tests, or smoke-test-only patterns found in the PR3 test diffs read directly (`test_specialties_list_pagination.py`, `test_checkpoint_list_allowlist.py`, `test_resolve_interaction_v2.py`, `test_appointment_decision_subgraph.py`). Every new/modified test calls production code (the node function or the compiled subgraph) and asserts on its concrete return value.

**Assertion quality**: ✅ All assertions verify real behavior

---

### Quality Metrics
**Linter**: ✅ No errors (`uv run ruff check .` — full repo)
**Type Checker**: ✅ No errors (`uv run mypy app/` — 294 files)

### Verdict
PASS
All 19 PR3 tasks complete with real code/test evidence, full unit suite green (1323/1323), ruff/mypy clean, no checkpoint/state/resolve_interaction/langgraph_agent_invoker regressions, no leak of internal observability fields into public/checkpointed state, safety-critical write gating unchanged and now structurally enforced, and the one edit-surface deviation is a legitimate, disclosed, non-weakening collateral fix. Only outstanding item is the maintainer's `size:exception` grant for the 400-line budget overage, which is a delivery-process gate, not a verification blocker.
