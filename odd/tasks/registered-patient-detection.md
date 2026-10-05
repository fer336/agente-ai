# registered-patient-detection

Objective: a patient who is already registered (DNI exists) is told "ya figurás en el sistema" and continues automatically (specialties / selected slot) instead of looping on name+DNI; clearer new-patient prompt and buttons.
Plan: /home/lucy/.claude/plans/cuando-un-paciente-no-sparkling-feather.md
TDD: strict, source: project config, runner: `uv run pytest`
Route: delegated direct (one writer, 4+ files)

## Tasks
- [x] T1 `find_patient_by_dni` in port, Dentalink gateway, fake gateway (+ gateway tests)
- [x] T2 Pre-check by DNI before proposing creation (text path) + "ya figurás" message + continue
- [x] T3 Race recovery (text + Flow paths) uses `find_patient_by_dni`; Flow pre-check
- [x] T4 New-patient prompt copy + dedicated buttons ("Soy paciente nuevo" / "Ya soy paciente")

## Evidence
- T1 976a7bb: RED 3 failed (AttributeError) -> GREEN `uv run pytest tests/unit/infrastructure` 553 passed
- T2 0d59484: RED 3 failed -> GREEN tests/unit 1641 passed. Text path pre-check by DNI; static "Ya figurás ... *name*" notice (name only); branching: CREATE no slot -> _offer_specialties, CREATE with slot -> _propose_selected_slot, other ops -> _offer_appointments
- T3 129c192: RED 4 failed -> GREEN tests/unit 1644 passed. Race recovery (text+Flow) via find_patient_by_dni; Flow pre-checks; _NEW_PATIENT_RACE_LOST_MESSAGE retired
- T4 0b3fc81: RED 3 failed (reminder-buttons test added with impl, no RED observed) -> GREEN tests/unit 1645 passed
- Final: ruff check . OK; mypy app/ OK (321 files); pytest tests/unit 1645 passed. Full `uv run pytest`: 4 failed + 3 errors in tests/integration (redis debounce lock x3, internal_eval_wiring), identical on base 1006bde (environmental).

