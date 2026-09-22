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

- [x] T5 Fix the review findings. (a) Align the day windows to clinic-local midnight so slots from 21:00 to 23:59 local are not dropped (a regression introduced by T2; the earlier "pre-existing" caveat was wrong). (b) Add a node-level test for the search range and the target of 18. (c) Remove the stray asyncio mark. Route: delegated.

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
- ~~Known caveat (pre-existing, not changed here): day windows are UTC-aligned...~~ **Correction (see T5 below): this was wrong — it is a regression T2 itself introduced (the aggregated windowing didn't exist before T2), not pre-existing. Fixed.**

- 2026-09-22: T4 implemented (route: delegated). Follow-up from parent review: T1's dedupe only covered the aggregated use case — the single-professional path (`SearchAvailabilityUseCase` -> `DentalinkAppointmentGateway.search_availability`) and the legacy `appointment.py` flow (both call the same `slot_rows`/`slots_list_message` builder from `appointment_selection.py`, so there was only ONE row builder to fix, not several) never deduped. Fixed at two layers:
  1. Source: `DentalinkAppointmentGateway.search_availability` now dedupes by derived id (keep first) before appending to `slots`, so the `limit` early-return counts real distinct slots, not raw duplicate rows.
  2. Last-line guard: `slot_rows` (the only row builder — `appointment.py`'s `_slots_list_message` IS `appointment_selection.slots_list_message`, which calls it) dedupes by row id before pagination, so a page's contents stay consistent even if a slot list somehow reaches it with a shared id.
  3. `SearchAvailabilityAnyProfessionalUseCase`'s own dedupe (T1) was kept, not removed: it's cheap, and it's the only place that catches a duplicate introduced ACROSS two different calendar-day gateway calls (the per-call gateway dedupe can't see across calls) — defense in depth, not redundant.
  4. `FakeDentalinkGateway.search_availability` updated to dedupe the same way, for test-fidelity with the real gateway.
  - A pre-existing test (`test_search_availability_stops_querying_once_it_has_enough_slots`) relied on its stub returning the exact same raw slot (same id) for every simulated day — that behavior was masking exactly this class of bug. Fixed the stub to vary the raw response per queried day (`_StubDentalinkClient` now supports a callable response) and kept the test's original intent (3 distinct days -> 3 distinct slots).
  - TDD: RED observed (4 failing tests: gateway never-duplicate, gateway limit-counts-deduped, fake-gateway dedupe, `slot_rows` dedupe) before implementation, GREEN after.
  - Verification: `uv run pytest -q` — 1543 passed, 82 skipped, 5 failed (the same pre-existing failures noted above, confirmed unrelated). `uv run ruff check .` — all checks passed. `uv run mypy app` — no issues in 320 source files. Commit: `f741cf7` fix(agent): dedupe slot ids on every path, not only the aggregated search.

- 2026-09-22: Parent spot check after T4: 486 passed (dentalink, agent, appointments). RDD assess (base `2b8affb`): risk `medium`, `review_due=true` (`slice_budget_reached`, 565 lines). The user declined the review for this candidate (`declined_this_candidate`). Delivery now follows ordinary repository policy.
- 2026-09-22: T5 implemented (route: delegated). Native review found 3 advisory findings; all fixed.
  - **(a) R3-utc-day-alignment-drops-late-clinic-slots (WARNING, regression from T2, not pre-existing).** Root cause: `_offer_any_professional_slots` built `now`/the search window in UTC, and `SearchAvailabilityAnyProfessionalUseCase` aligns its per-day windows to midnight in whatever tz it's given — so it aligned to UTC midnight. A UTC-3 clinic slot at 21:00-23:59 local falls on the NEXT calendar date in UTC, so it fell into the wrong day's window and the real gateway asked Dentalink for the wrong `fecha`, losing it entirely.
    - Design choice: added `clinic_timezone: tzinfo` as a `@property` on the `AppointmentGateway` Protocol itself (`app/domain/repositories/gateways.py`), implemented by `DentalinkAppointmentGateway` (returns its existing `self._clinic_timezone`, sourced from `settings.clinic_timezone` via `app/api/dependencies/gateways.py`) and `FakeDentalinkGateway` (defaults to UTC, overridable). `_offer_any_professional_slots` already receives `appointment_gateway` as a constructor-injected PORT (domain layer) — reading `.clinic_timezone` off it needed no new parameter threaded through `graph.py`/`appointment.py`/`langgraph_agent_invoker.py`/DI wiring (5+ files), and no infrastructure/`Settings` import in the agent layer. `now = datetime.now(appointment_gateway.clinic_timezone)` replaces `datetime.now(UTC)`; the use case itself needed NO change (it already aligns to midnight in whatever tz `date_range` carries, as designed in T2).
    - Also fixed defense-in-depth: `DentalinkAppointmentGateway.search_availability`'s own `day`/`last_day` computation now converts to `self._clinic_timezone` before taking `.date()`, instead of taking it from whatever tz the caller's `date_range` happens to carry — protects any OTHER caller (e.g. the single-professional path) that might still pass a UTC-anchored range.
    - RED: `test_a_valid_specialty_pick_finds_a_late_clinic_local_slot` (subgraph, via a `_FechaScopedGateway` double that simulates Dentalink's real per-`fecha` indexing — a plain `FakeDentalinkGateway`/`date_range.contains()` double CANNOT reproduce this bug, since it never simulates a day-scoped query losing a slot) and `test_search_availability_derives_fecha_from_the_clinic_timezone_not_the_callers` (real gateway) both failed before the fix, passed after.
  - **(b) R3-subgraph-range-untested (SUGGESTION).** Added `test_offer_any_professional_slots_passes_a_clinic_local_range_and_the_real_target`: monkeypatches `SearchAvailabilityAnyProfessionalUseCase` with a spy, asserts `date_range.start` is clinic-tz (not UTC — checked via `utcoffset()`), `date_range.end == clinic-local-midnight-today + _AGGREGATE_SEARCH_WINDOW`, and `target_slot_count == 18`.
  - **(c) R3-stray-asyncio-mark-on-helper (SUGGESTION).** Removed the stray `@pytest.mark.asyncio` above the sync `_one_slot_for_the_queried_day` helper in `test_appointment_gateway.py`; the actual async test right below it already carries its own mark, so nothing needed re-adding.
  - Corrected the T4-era "pre-existing caveat" line above: it was this exact bug, introduced by T2, not pre-existing (T2 is what introduced the calendar-day-aligned windowing in the first place).
  - TDD: RED observed (3 failing tests total across (a)/(b): 2 behavioral RED, 1 RED via a missing `clinic_timezone` kwarg surfacing the plumbing gap) before implementation, GREEN after.
  - Verification: `uv run pytest -q` — 1546 passed, 82 skipped, 5 failed (the same pre-existing failures noted above, confirmed unrelated). `uv run ruff check .` — all checks passed. `uv run mypy app` — no issues in 320 source files. Commit: see below.

## Next step
Archive once the parent orchestrator reviews; the 5 pre-existing failing tests (DI/fake-gateway defaults, unrelated to this fix) are a separate, out-of-scope issue for the parent to triage.
