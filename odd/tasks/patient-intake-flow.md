# Single WhatsApp Flow for patient / new-patient data

## Objective

One WhatsApp Flow with two paths: "Are you a patient?" Yes -> name + DNI (verification); No -> full
registration (name, DNI, email, obra social). Create it in Meta through YCloud, validate it, send it.

## Problem

Two separate single-screen Flows exist (verification, registration). The bot picks one per stage. The
user wants one Flow that serves both cases.

## Scope

- T1 `build_patient_intake_flow_json` in `app/infrastructure/ycloud/flows.py` (schema 6.2, one terminal
  screen `DATOS_PACIENTE`, `If` blocks for the "no" path; fall back to two screens if Meta rejects `If`).
- T2 Create with `publish=false`, read Meta validation errors, then publish (`YCloudClient.create_flow`).
- T3 Setting `ycloud_patient_intake_flow_id`, wired like the existing flow ids; env template entry.
- T4 `appointment.py` consumes the reply and branches on `es_paciente`; old two-flow path stays when the
  new id is empty.
- T5 `POST /admin/api/flows/create` also creates the new Flow.

## Constraints

Strict TDD; runner `uv run pytest`; `uv run ruff check app tests`, `ruff format --check`, `mypy` on
touched files. Patient-facing text in Rioplatense Spanish, code/docs in English. No AI attribution in
commits; Conventional Commits. Real Meta calls and sends to +542254423359 need the user's go-ahead.

## Tasks

- [x] T1 Flow JSON builder + tests (a237cdc; RED import error, GREEN 13 passed in test_flows.py)
- [x] T2 Draft-then-publish creation + tests (a237cdc; `create_flow` already defaulted to publish=False and put the response body in YCloudAPIError; added 2 pinning tests, no RED possible, no code change)
- [x] T3 Setting + wiring + env template (setting, env template, graph kwarg in a237cdc; invoker + gateways pass-through by the parent; 3464 passed, ruff and mypy clean)
- [x] T4 Reply consumption branch + tests (a237cdc; 8 new tests in tests/unit/agent/nodes/test_patient_intake_flow.py, RED TypeError then GREEN; tests/unit/agent 1608 passed; no new stage added)
- [x] T5 Admin route + tests (a237cdc; tests/unit/api/routes/test_admin.py 29 passed; full tests/unit 3464 passed)
- [ ] T6 Live: create draft in Meta, validate, publish, send to the test number

## Route declaration

Writer trigger (2+ non-trivial files) -> one bounded writer for T1-T5. T6 is run by the parent.

## Progress

Worktree `../agente-ai-worktrees/patient-flow`, branch `feat/patient-intake-flow`. Engram mirror
`odd/patient-intake-flow/tasks`: PENDING (MCP mem_save fails with several active runtime sessions).
Note: PR #212 (appointment.py identification changes) is not merged yet; expect a rebase.

## Next step

Delegate T1-T5 to a writer.
