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
- [~] T6 Live: draft `4672565303067581` created in Meta and validated (validationErrors empty). Publish refused by Meta: 400 "Blocked by Integrity" (code 139000, subcode 4233020). Not sent. First draft `1004024948763559` was invalid (layout must be SingleColumnLayout > Form); it remains as a draft in the account.
- [x] T7 Flow JSON: obra social Dropdown (agreement names + `particular`, deduped, 30-char titles, 200 cap), optional `plan` in a nested `If` (`${form.obra_social} != '' && ${form.obra_social} != 'particular'`), `plan` in the completion payload, logo loader + alt-text "Smiling Dental Studio" (68a8970; RED ImportError, GREEN 22 passed in test_flows.py)
- [x] T8 Backend consumption: `particular` option id (case-insensitive) links the "Particular" convenio and never keeps a plan; other insurers keep `insurance_provider`/`insurance_plan` in `collected_data` (local only) (8a39f8a; 5 RED, then 14 passed; tests/unit/agent 1651 passed)
- [x] T9 `YCloudClient.get_flow_preview_url` (defensive response parsing, `YCloudAPIError` when the URL is missing) (1922294; RED 11 failed, GREEN 38 passed)
- [x] T10 `POST /admin/api/flows/intake-draft` (draft, `publish=False`, live convenios, logo, returns `{flow_id, preview_url}`); `/flows/create` also passes the convenios and logo to the intake builder (RED 4 failed, GREEN 32 passed)

Decisions T7-T10: Meta allows nested `If` up to 3 levels from Flow JSON 4.0 (docs: developers.facebook.com
/docs/whatsapp/flows/reference/components), so the plan `If` is nested inside the new-patient `If`. Dropdown
label limit is 20 chars, hence "Obra social". Dropdown ids are the agreement names (unmodified), only titles
are truncated. "Particular" is listed first so the 200 cap never drops it. An unselected Dropdown's value in
`If` conditions is unverified, hence the extra `!= ''` guard; Meta validation of the draft is still pending.
The preview response shape is unverified (YCloud docs page not machine readable). `fix/particular-no-plan` is
NOT merged into main: Particular is linked through the ordinary name lookup of a convenio named "Particular".

## Route declaration

Writer trigger (2+ non-trivial files) -> one bounded writer for T1-T5 and one for T7-T10. T6 is run by the parent.

## Progress

Worktree `../agente-ai-worktrees/patient-flow`, branch `feat/patient-intake-flow`. Engram mirror
`odd/patient-intake-flow/tasks`: PENDING (MCP mem_save fails with several active runtime sessions).
Note: PR #212 (appointment.py identification changes) is not merged yet; expect a rebase.

## Next step

Delegate T1-T5 to a writer.
