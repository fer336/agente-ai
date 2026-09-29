# View appointment summary

## Objective

"📋 Ver mi cita" (and typed equivalents such as "qué turnos tengo") shows the patient a
clear summary of their upcoming appointments, then offers actions. Today it is routed as a
reschedule (`OPERATION_VIEW_PAYLOAD` → `RESCHEDULE_APPOINTMENT_ACTION`,
`app/agent/nodes/appointment.py:284`, `_OPERATION_BY_MENTION["view"]`), so the patient
only sees date buttons and, on tap, lands in a rescheduling flow they did not ask for.

## Behavior

1. Identification as today. It is skipped when the patient is already remembered in the
   conversation (`patient_identity`, v0.42.4).
2. No upcoming appointments → the existing no-appointments reply with the handoff buttons.
3. Upcoming appointments → one message:
   - a short LLM-built intro (no greeting, varied);
   - a deterministic list, one "- " line per appointment: date (weekday dd/mm), time,
     professional and specialty when available. It is built by code so the details are
     always exact.
4. Buttons: "🔄 Reagendar", "❌ Cancelar", "Menú principal".
   - Reagendar / Cancelar with one appointment → go straight into the existing
     reschedule / cancel flow for that appointment.
   - With several appointments → reuse the existing appointment-selection step for that
     operation.
   - Menú principal → the existing main-menu reset (keeps the patient identity).

## Constraints

- Strict TDD: observed RED before implementation, then GREEN, then REFACTOR.
- Runner: `uv run pytest`; also `uv run ruff check .`, `uv run mypy app/`,
  `uv run ruff format --check <changed files>`.
- Known environmental failures: `test_internal_eval_wiring` (1), `test_redis_debounce_lock.py` (3).
- English artifacts, Spanish patient copy, no AI attribution in commits.
- Delivery: `docs/pr-release-workflow.md` (a `feat(...)` title → minor release).

## Tasks

- [x] T1 — Distinct view operation with a summary message and Reagendar / Cancelar /
  Menú principal actions. Route: delegated direct (writer trigger: 2+ files). Commit: see `git log` (feat(appointments): show an appointment summary on ver mi cita).

## Acceptance criteria

- Ver mi cita shows the details (date, time, professional, specialty if available) and the
  3 buttons; nothing is rescheduled unless the patient taps Reagendar.
- Reagendar / Cancelar reach the existing flows, directly when there is one appointment.
- Reschedule and cancel entry points behave exactly as before.

## Progress

- Branch `feat/view-appointment-summary` from origin/main 4a7dd0c (v0.42.4).
- T1 RED: `tests/unit/agent/nodes/test_view_appointments.py` first failed on import
  (`STAGE_AWAITING_VIEW_ACTION` missing); after adding the constants and the view
  mappings only, 16 behavior tests failed (summary + 3 buttons, one-appointment
  Reagendar/Cancelar, multi-appointment selection, unclear text, lost context,
  reschedule framing, intro intent, remembered patient, static fallback, cap).
- T1 GREEN: all new tests pass; `uv run pytest` 1863 passed, only the excused
  failures remain; ruff check, mypy and ruff format --check on changed files clean.
- Specialty decision: shown when available. `Professional.specialty_id` comes from the
  `list_professionals()` call already made for the names, and names resolve through the
  existing `ListSpecialtiesUseCase`; no new gateway call. Omitted when the professional
  has no specialty.
- The summary lists at most 3 appointments (reschedule/cancel selection sends one
  WhatsApp button per appointment, max 3) and adds "Y N turnos más." when there are more.

## Next step

Open the pull request (`docs/pr-release-workflow.md`).
