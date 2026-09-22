# Slot list: duplicate row ids and list sizing

## Objective
The "soonest slots across all professionals" list must reach the patient on WhatsApp. It should show up to the next 18 available slots within a 7-day window.

## Problem
- YCloud accepts the outbound list (HTTP 200), but WhatsApp rejects it asynchronously with `[131009] Duplicated row id`. The patient never sees the slot list, so the booking flow looks stuck after picking a specialty.
- Row ids are `SELECT_SLOT:<slot.id>`. `slot_from_agenda` uses Dentalink's raw agenda `id`, which is not unique across the slots of one aggregated search.
- `SearchAvailabilityAnyProfessionalUseCase` walks windows anchored at `now`, not at calendar days. Each window therefore spans two calendar dates, and the gateway makes one `/v5/agendas` request per date, so each window costs two Dentalink requests.
- Row titles are clamped to 24 chars. The user requires a 20-char limit to avoid errors.

## Scope / constraints
- Keep `_AGGREGATE_SEARCH_WINDOW = 7 days`.
- Target 18 slots (2 full pages of 9 rows, within Meta's 10-row cap per list, including "Ver más" / "Volver").
- Make exactly one Dentalink request per calendar day, and stop as soon as the target is reached.
- Every row id in a list is unique, and so is every slot id in an aggregated result.
- Slot row titles are at most 20 chars and still show weekday, date and time (e.g. `🕐 Mié 24/09 14:30`).
- Booking does not send `slot.id` to Dentalink (it uses professional/date/time), so deriving the id is safe.
- TDD: strict (session config). Runner: `pytest` (pyproject). Also run `ruff check` and `mypy`.
- Out of scope (pending user decision): a `SPECIALTY:` payload arriving while stage is `awaiting_slot_selection` is treated as a stale slot pick.

## Tasks
- [x] T1 Unique slot ids: derive a deterministic id from professional + start, and dedupe the aggregated results. Route: delegated (writer trigger, 2+ files).
- [x] T2 One request per calendar day, and a target of 18 slots. Route: delegated (same writer).
- [x] T3 Slot row titles at most 20 chars, with an abbreviated weekday. Route: delegated (same writer).

## Acceptance criteria
- An aggregated search whose raw agenda rows share ids yields unique slot ids and unique list row ids.
- A 7-day search makes at most 7 `/v5/agendas` requests (one per date) and returns at most 18 slots, sorted.
- Every slot row title is at most 20 chars.
- The full test suite, ruff and mypy pass.

## Progress / evidence
- 2026-09-22: Root cause confirmed from a YCloud screenshot (`131009 Duplicated row id`). Branch `fix/slot-list-duplicate-row-ids` created from `origin/main`.
- 2026-09-22: T1+T2 implemented (route: delegated). `slot_from_agenda` now derives `slot.id` from `f"{professional_id}-{start:%Y%m%d%H%M}"`, ignoring the raw agenda `id`. `SearchAvailabilityAnyProfessionalUseCase.execute` dedupes by id (keep first) and walks calendar-day-aligned windows (aligned to the next midnight in the caller's own tz, not now-anchored 24h chunks), so the real gateway issues at most one `/v5/agendas` request per window. `_offer_any_professional_slots` now builds its search range from today's midnight so the window spans exactly `_AGGREGATE_SEARCH_WINDOW.days` (7) calendar dates instead of 8. `_AGGREGATE_TARGET_SLOTS` raised to 18. TDD: RED observed (6 failing tests) before implementation, GREEN after. Commit: `9daadca` fix(agent): dedupe slot ids and cap aggregated search to one request per day.
  - Also fixed 2 pre-existing `test_appointment_gateway.py` tests whose assertions depended on the old raw-id behavior (same commit).
- 2026-09-22: T3 implemented (route: delegated). `slot_rows` now abbreviates the weekday to 3 letters and clamps titles to a dedicated `_SLOT_ROW_TITLE_MAX_CHARS = 20` (not the shared 24-char `TITLE_MAX_CHARS`, left untouched — a global change would have clipped longer specialty/professional names). TDD: RED observed (2 failing tests) before implementation, GREEN after. Commit: see this same commit (doc update bundled with T3's code change).
- Verification (full run, after all 3 tasks): `uv run pytest -q` — 1539 passed, 82 skipped, 5 failed (pre-existing on `origin/main` before this branch's changes, confirmed via `git stash`: `test_internal_eval_wiring.py::test_get_evaluate_chat_turn_use_case_wires_a_working_isolated_agent` and 4 tests in `test_gateway_dependency.py`, all about DI defaulting to fakes — unrelated to this change). `uv run ruff check .` — all checks passed. `uv run mypy app` — no issues in 320 source files.

## Next step
Archive once the parent orchestrator reviews; the 5 pre-existing failing tests (DI/fake-gateway defaults, unrelated to this fix) are a separate, out-of-scope issue for the parent to triage.
