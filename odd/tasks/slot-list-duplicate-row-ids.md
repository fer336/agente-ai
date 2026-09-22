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
- [x] T4 Duplicate slot ids must be impossible on every path (single-professional search + legacy `appointment.py` flow), not just the aggregated use case. Route: delegated (same writer).

## Acceptance criteria
- An aggregated search whose raw agenda rows share ids yields unique slot ids and unique list row ids.
- A 7-day search makes at most 7 `/v5/agendas` requests (one per date) and returns at most 18 slots, sorted.
- Every slot row title is at most 20 chars.
- No path (aggregated, single-professional, or legacy `appointment.py`) can ever hand a slot list with duplicate ids to a `ListRow` builder: deduped at the gateway (source), and again at the row-building layer (last-line guard).
- The full test suite, ruff and mypy pass.

## Progress / evidence
- 2026-09-22: Root cause confirmed from a YCloud screenshot (`131009 Duplicated row id`). Branch `fix/slot-list-duplicate-row-ids` created from `origin/main`.
- 2026-09-22: T1+T2 implemented (route: delegated). `slot_from_agenda` now derives `slot.id` from `f"{professional_id}-{start:%Y%m%d%H%M}"`, ignoring the raw agenda `id`. `SearchAvailabilityAnyProfessionalUseCase.execute` dedupes by id (keep first) and walks calendar-day-aligned windows (aligned to the next midnight in the caller's own tz, not now-anchored 24h chunks), so the real gateway issues at most one `/v5/agendas` request per window. `_offer_any_professional_slots` now builds its search range from today's midnight so the window spans exactly `_AGGREGATE_SEARCH_WINDOW.days` (7) calendar dates instead of 8. `_AGGREGATE_TARGET_SLOTS` raised to 18. TDD: RED observed (6 failing tests) before implementation, GREEN after. Commit: `9daadca` fix(agent): dedupe slot ids and cap aggregated search to one request per day.
  - Also fixed 2 pre-existing `test_appointment_gateway.py` tests whose assertions depended on the old raw-id behavior (same commit).
- 2026-09-22: T3 implemented (route: delegated). `slot_rows` now abbreviates the weekday to 3 letters and clamps titles to a dedicated `_SLOT_ROW_TITLE_MAX_CHARS = 20` (not the shared 24-char `TITLE_MAX_CHARS`, left untouched — a global change would have clipped longer specialty/professional names). TDD: RED observed (2 failing tests) before implementation, GREEN after. Commit: see this same commit (doc update bundled with T3's code change).
- Verification (full run, after all 3 tasks): `uv run pytest -q` — 1539 passed, 82 skipped, 5 failed (pre-existing on `origin/main` before this branch's changes, confirmed via `git stash`: `test_internal_eval_wiring.py::test_get_evaluate_chat_turn_use_case_wires_a_working_isolated_agent` and 4 tests in `test_gateway_dependency.py`, all about DI defaulting to fakes — unrelated to this change). `uv run ruff check .` — all checks passed. `uv run mypy app` — no issues in 320 source files.

- Parent spot check: `uv run pytest -q tests/unit/infrastructure/dentalink tests/unit/application/appointments tests/unit/agent` — 482 passed. RDD assess (base `2b8affb`, committed-only): risk `medium`, `review_due=false` (`under_budget`, 345 lines); pending in slice.
- Known caveat (pre-existing, not changed here): day windows are UTC-aligned and the gateway takes `.date()` from them without converting to the clinic tz, so a clinic slot at or after 21:00 local (UTC-3) falls outside its day's window.

- 2026-09-22: T4 implemented (route: delegated). Follow-up from parent review: T1's dedupe only covered the aggregated use case — the single-professional path (`SearchAvailabilityUseCase` -> `DentalinkAppointmentGateway.search_availability`) and the legacy `appointment.py` flow (both call the same `slot_rows`/`slots_list_message` builder from `appointment_selection.py`, so there was only ONE row builder to fix, not several) never deduped. Fixed at two layers:
  1. Source: `DentalinkAppointmentGateway.search_availability` now dedupes by derived id (keep first) before appending to `slots`, so the `limit` early-return counts real distinct slots, not raw duplicate rows.
  2. Last-line guard: `slot_rows` (the only row builder — `appointment.py`'s `_slots_list_message` IS `appointment_selection.slots_list_message`, which calls it) dedupes by row id before pagination, so a page's contents stay consistent even if a slot list somehow reaches it with a shared id.
  3. `SearchAvailabilityAnyProfessionalUseCase`'s own dedupe (T1) was kept, not removed: it's cheap, and it's the only place that catches a duplicate introduced ACROSS two different calendar-day gateway calls (the per-call gateway dedupe can't see across calls) — defense in depth, not redundant.
  4. `FakeDentalinkGateway.search_availability` updated to dedupe the same way, for test-fidelity with the real gateway.
  - A pre-existing test (`test_search_availability_stops_querying_once_it_has_enough_slots`) relied on its stub returning the exact same raw slot (same id) for every simulated day — that behavior was masking exactly this class of bug. Fixed the stub to vary the raw response per queried day (`_StubDentalinkClient` now supports a callable response) and kept the test's original intent (3 distinct days -> 3 distinct slots).
  - TDD: RED observed (4 failing tests: gateway never-duplicate, gateway limit-counts-deduped, fake-gateway dedupe, `slot_rows` dedupe) before implementation, GREEN after.
  - Verification: `uv run pytest -q` — 1543 passed, 82 skipped, 5 failed (the same pre-existing failures noted above, confirmed unrelated). `uv run ruff check .` — all checks passed. `uv run mypy app` — no issues in 320 source files. Commit: `f741cf7` fix(agent): dedupe slot ids on every path, not only the aggregated search.

## Next step
Archive once the parent orchestrator reviews; the 5 pre-existing failing tests (DI/fake-gateway defaults, unrelated to this fix) are a separate, out-of-scope issue for the parent to triage.

- 2026-09-22: Parent spot check after T4: 486 passed (dentalink, agent, appointments). RDD assess (base `2b8affb`): risk `medium`, `review_due=true` (`slice_budget_reached`, 565 lines). The user declined the review for this candidate (`declined_this_candidate`). Delivery now follows ordinary repository policy.
