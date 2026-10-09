# Confirm patient data before the lookup

## Objective

After the patient types full name + DNI (existing-patient identification), always show the
data back and ask for confirmation (Confirmar / Modificar) BEFORE any Dentalink lookup.
Confirmar runs the existing lookup and continues the flow where it was. Modificar asks for
the data again; the patient retypes, the confirmation is shown again, and so on until
Confirmar.

## Problem

Observed live (2026-10-08): the patient sent "Pedro cassera", then DNI `30231313`, then a typo
correction `30131313`. `ingest_message.py:638` joins grouped messages with newlines and
`_DNI_PATTERN.search` (`appointment.py:376`) keeps the FIRST digit run, so the lookup used the
wrong DNI, found nobody and offered "Registrarme / Probar otro dato / Administración".

## Why

A typo must never reach the lookup or push the patient into registering. A confirmation turn
lets the patient fix what the bot understood (also covers names mangled by the LLM extraction).

## Scope

- Typed-text identification only (`STAGE_AWAITING_IDENTIFICATION` branch, `appointment.py` ~4223-4482),
  inserted right after DNI validation passes and before `identify_patient.execute` (~4448).
- New stage `awaiting_identification_confirmation` keeping `identification_full_name` and
  `identification_dni` in `collected_data`.
- Two new payloads in `app/domain/value_objects/menu_payloads.py` (Confirmar / Modificar).
- Confirmar -> existing lookup + `_continue_as_registered_patient` / not-found choice, unchanged.
- Modificar -> clear the identification pieces, short message asking to resend the data
  correctly, stage back to `STAGE_AWAITING_IDENTIFICATION`.
- Free text at the confirmation stage: parseable name+DNI = treated as a modification
  (replace pieces, show confirmation again); anything else = repeat the buttons.
- Out of scope: WhatsApp Flow verification variant (~`A:4036`), re-entry paths that already have
  confirmed data (`_identify_existing_patient`), "last DNI wins" extraction change, first-visit
  intake (it already has its own review step).

## Constraints

- Static, fixed wording for the confirmation (no LLM): it echoes the patient's data.
- Update every stage set that lists identification stages (`_DATA_COLLECTION_STAGES`,
  `_NAVIGABLE_STAGES`, third-party guard exemptions in `resolve_interaction.py`).
- Button titles <= 20 chars, max 3 buttons. Set `INTERACTIVE_SELECTION` input state like the
  not-found stage does.
- TDD: strict (RED observed before implementation). Runner: `uv run pytest`. Checks:
  `uv run ruff check app tests`, `uv run ruff format --check <touched>`, `uv run mypy <touched>`.
- Artifacts in English; user-facing patient text in Rioplatense Spanish.
- No `Co-Authored-By` / AI attribution; Conventional Commits.

## Tasks

- [x] T1 Payload constants + stage constant + confirmation message/buttons builder
- [x] T2 Stage branch: show confirmation instead of the direct lookup; handle Confirmar,
      Modificar, free text at the stage
- [x] T3 Register the new stage in the stage sets / routing tables
- [x] T4 Update the tests that assert direct lookup (`test_patient_not_found.py`,
      `test_appointment_node.py` two-message dni/name flows, `test_data_stage_routing.py`) and the
      evals (`evals/datasets/audit_followups.yaml`, `appointments.yaml`) with the confirm turn

## Acceptance criteria

- Name+DNI typed -> confirmation message with both values and Confirmar/Modificar; no Dentalink call yet.
- Confirmar -> lookup runs; found -> flow continues where it was; not found -> existing choice.
- Modificar -> asks to resend; retyped data -> confirmation again; loops until Confirmar.
- Two DNIs in one grouped message show the confirmation (patient can Modificar).
- Full unit suite green; ruff + mypy clean on touched files.

## Route declaration

Mapping trigger fired (4+ files): one narrow mapper delegated (done, report folded into this
document). Writer trigger fires (2+ non-trivial files): one bounded writer delegated for T1-T4.

## Delivery

Forecast ~300-450 authored changed lines (tests dominate). Strategy: `ask-on-risk` (default),
one PR. Branch: `fix/confirm-patient-data` (worktree `../agente-ai-worktrees/confirm-patient-data`).
Push / PR / merge stay the user's decision.

## Progress

- Mapper report received; T1-T4 implemented in commit `aeeb60c` (feat(agent): confirm the patient's name
  and DNI before looking them up). Strict TDD: RED observed (new tests failed on the missing
  confirmation, then on the unregistered stage in `resolve_interaction`), then GREEN.
- Verification observed: `uv run pytest tests/unit -q` 3447 passed; `uv run pytest tests/unit/evals -q`
  110 passed; `uv run ruff check app tests` clean; `ruff format --check` clean on touched files
  (`test_checkpoint_list_allowlist.py` was already unformatted on main, left as is); `uv run mypy`
  on the 3 touched app files clean.
- Decision beyond the plan: when `collected_data` already holds an identified `patient`
  (re-entry via `_identify_existing_patient` after an earlier lookup), the lookup runs directly;
  re-entry with only remembered, unconfirmed pieces now shows the confirmation.
- Engram mirror `odd/confirm-patient-data/tasks`: PENDING (mem_save failed: several active runtime
  sessions match the project). Resync when available.

## Next step

Push / PR / merge are the user's decision.
