# Specialty slots, no professional list

## Objective

When a patient asks for an appointment of a specialty, the agent shows the next 10 free slots
(soonest first, across all professionals of that specialty) and never asks the patient to choose
a professional.

## Problem

Live test (2026-10-01): "Quería un turno de ortodoncia" -> first-visit question -> identification
-> the agent asked "con qué profesional preferís atenderte" and showed an "Elegí profesional" list.
The owner's rule is that professionals are never shown, only slots.

Root cause (mapping of v0.48.0): the free-text `specialty_mention` branch of the appointment node
(`app/agent/nodes/appointment.py`, ~4500-4511) still calls `_offer_professionals`. The specialties
node (`app/agent/nodes/specialties.py`), the "no slots" fallback ("Elegir profesional" in
`appointment_decision_subgraph.py` `_offer_browse_choice`/`choose_browse_mode`) and the explicit
professional mention (one-row professional list) are other leaks. The specialty list tap and the
FAQ_BOOK / preselected General paths already show aggregated slots.

## Scope

- T1: `specialty_mention` (and the specialties node, "quiero un médico general") go straight to the
  aggregated slots of that specialty (reuse `_offer_any_professional_slots`), after the first-visit
  question and identification as today. Show exactly 10 slots (`_AGGREGATE_TARGET_SLOTS`), no
  professional names on the rows.
- T2: remove the other professional-list leaks of the create flow: the no-slots fallback offers
  "Otra especialidad" (and the menu / administration), not "Elegir profesional"; an explicit
  professional mention ("turno con la Dra. X") goes straight to that doctor's slots instead of a
  one-row professional list (decision: honors the patient's request and still shows only slots).
- Out of scope: the reschedule flow ("cambiar profesional"), deleting the old stage constants.
  Old in-flight checkpoints (`STAGE_AWAITING_PROFESSIONAL_SELECTION`,
  `STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE`, `STAGE_AWAITING_NO_SLOTS_CHOICE`) must keep resolving:
  keep the constants and mappings and make those stages convert to the slots screen.

## Constraints

- Branch `fix/specialty-slots-no-professionals` from origin/main (ada7701, v0.48.0), worktree
  `../agente-ai-worktrees/specialty-slots-no-professionals`.
- Strict TDD (RED -> GREEN -> REFACTOR). Runner: `uv run pytest`; also `uv run ruff check .`,
  `uv run mypy app/`, `uv run ruff format --check <changed files>`.
- Known environmental failures: `tests/integration/test_redis_debounce_lock.py` (3).
- English artifacts, Spanish patient copy, no AI attribution in commits.
- WhatsApp lists hold at most 10 rows: 10 slots means no "Ver más" / "Volver" row.
- Delivery: `docs/pr-release-workflow.md`, `fix(...)` title (patch release).

## Tasks

- [x] T1 — specialty_mention and specialties node show the next 10 slots. Route: delegated direct. Commit: see Progress.
- [x] T2 — remove the remaining professional-list leaks of the create flow. Route: delegated direct.

## Acceptance criteria

- "Quiero un turno de ortodoncia" (new patient: after the first-visit question and identification;
  known patient: immediately) shows a list of up to 10 slots and no professional list.
- No path of the create flow shows a professional list; old checkpoints still resolve.

## Progress

- Worktree created (2026-10-01).
- T1 done. RED observed: ImportError for the new `SPECIALTY_SLOTS_REQUEST_KEY` (subgraph tests), 5 behavioral
  failures in the subgraph tests (target 10, single page, hint text, stale LIST_MORE, requested specialty),
  3 failures in test_appointment_node.py (named specialty / known patient / slot picked), 16 in the
  specialties node tests (new constructor arg + slots), 1 in the flows eval replay (live-bug scenario).
  GREEN: full suite 2562 passed (3 known redis-lock tests deselected), ruff check and mypy clean.
  Decisions: new one-shot flag `show_specialty_slots` hands a resolved specialty to the decision subgraph
  (route_entry -> choose_specialty -> `_offer_any_professional_slots`); the escape hint ("menú"/"administración")
  is appended verbatim to the LLM text; aggregated screen = one page, no nav row when <= 10 slots;
  FakeLLMProvider now reports a `specialty_mention` for common specialty names so the eval can replay the live bug.
  Read-only catalog browse in the specialties node (no booking context) still lists professionals on purpose.
- T2 done. RED observed: 13 failures in the subgraph tests (fallback buttons, stale CHOOSE_PROFESSIONAL tap,
  in-flight PROFESSIONAL_SELECTION conversion, explicit professional straight to slots) and 10 in the appointment
  node tests (explicit professional, no-slots checkpoint, nav target, repair path) before the implementation.
  GREEN: full suite 2586 passed (3 known redis-lock tests deselected), ruff check and mypy clean.
  Decisions: create flow never lists professionals (`_offer_professionals` in appointment.py and `choose_professional`,
  `search_availability_node`, `NO_SLOTS_CHOICE` handler convert to the specialty's next slots when
  `rescheduling_appointment_id` is absent); RESCHEDULE keeps its professional list on purpose (commented where it remains).
  Explicit professional mention (appointment node and specialties node) -> that professional's slots; no slots ->
  aggregated slots of the same specialty with an LLM-worded notice (static fallback). No-slots fallback buttons:
  Otra especialidad / Menu principal / Administracion. Read-only catalog browse in the specialties node keeps its list.

## Next step

Review and PR (`fix(appointments)` per docs/pr-release-workflow.md); push and PR are the owner's decision.