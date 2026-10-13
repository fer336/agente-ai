# Ask only for the wrong piece of identification data

## Objective

When the patient says their name/DNI is wrong, the bot asks ONLY for the wrong piece, keeps the
other one, and shows the confirmation again. It never asks for everything again.

## Problem

- The Confirmar / Modificar step (#210): Modificar clears BOTH pieces and asks "tu nombre completo
  y tu DNI" again.
- "Probar otro dato" (patient not found, `PATIENT_NOT_FOUND_RETRY_PAYLOAD`, `appointment.py` ~4715)
  also clears both pieces and calls `_begin_identification` (asks everything).
- Pre-lookup branches (missing name, missing DNI, invalid DNI, incomplete name) ALREADY ask only for
  the failing piece and keep the other in `collected_data`; they stay unchanged.

## Why

User rule: "cuando un dato esta mal debe pedir solo el dato que esta mal no debe volver a pedir todo".
Re-asking both pieces makes the patient retype what was right.

## Scope

- New stage `awaiting_identification_field_choice` and two payloads in
  `app/domain/value_objects/menu_payloads.py`: fix name / fix DNI.
- Modificar tap -> "which piece do you want to correct?" with two buttons (Nombre / DNI), BOTH
  pieces kept in `collected_data`, `INTERACTIVE_SELECTION` input state. Reuse the shape of the
  first-visit intake review/choose-field step (`app/agent/first_visit_intake_subgraph.py`).
- "Probar otro dato" tap -> the same chooser (both pieces kept) instead of clearing both.
- Tap Nombre -> drop only the name, stage `awaiting_identification`, ask for the name only with the
  existing `_ask_name_only_message`; tap DNI -> drop only the DNI, ask for the DNI only with
  `_ask_dni_only_message`. The existing "one piece in hand, the other missing" branches then take
  the answer and lead to the confirmation again (verify this in the code before relying on it).
- Free text at the chooser stage: parseable name+DNI (or a single valid piece) = a correction (same
  handling as at the confirmation stage); anything else repeats the chooser buttons.
- Register the new stage in the same stage sets the confirmation stage is in (`_NAVIGABLE_STAGES`,
  `_DATA_COLLECTION_STAGES` in `resolve_interaction.py`, checkpoint allowlist test, etc.).
- Out of scope: the DNI extraction regex (6+ digit candidates, last 7-8 digit run wins; already in
  commit 43e8e51 of this branch), WhatsApp Flow variant, first-visit intake.

## Constraints

- Fixed wording (no LLM) for the chooser message; patient-facing text in Rioplatense Spanish,
  everything else in English. Button titles <= 20 chars, max 3 buttons.
- Strict TDD (RED observed first). Runner `uv run pytest`. Checks: `uv run ruff check app tests`,
  `uv run ruff format --check <touched>`, `uv run mypy <touched app files>`.
- No `Co-Authored-By` / AI attribution; Conventional Commits.

## Tasks

- [x] T1 Payloads + stage constant + chooser message/buttons
- [x] T2 Modificar and "Probar otro dato" -> chooser; Nombre / DNI taps ask only that piece and keep
      the other; free text at the chooser stage
- [x] T3 Register the new stage in the stage sets / routing tables
- [x] T4 Update tests/evals that assume Modificar or "Probar otro dato" re-ask everything; add a
      regression test that missing/invalid pieces keep asking only for that piece

## Acceptance criteria

- Modificar and "Probar otro dato" show the chooser; neither clears both pieces.
- Choosing Nombre asks only for the name and keeps the DNI; choosing DNI asks only for the DNI and
  keeps the name; the confirmation is shown again afterwards; Confirmar still runs the lookup.
- Full unit suite green; ruff + mypy clean on touched files.

## Route declaration

Writer trigger (2+ non-trivial files) -> one bounded writer. Parent spot-checks the result.

## Delivery

Same branch and PR as the "last number is the DNI" fix (`fix/dni-last-number`, worktree
`../agente-ai-worktrees/dni-last`). `ask-on-risk`. Push / PR / merge stay the user's decision.

## Progress

- Branch has commit 43e8e51 (last number is the DNI). Engram mirror `odd/ask-only-wrong-data/tasks`:
  PENDING (mem_save fails with several active runtime sessions).
- T1-T4 done in the feature commit (see `git log`; subject `feat(agent): ask only for the wrong
  identification data instead of everything again`). Route: delegated writer.
- Evidence (observed): RED first (20 tests failed on behavior after adding constants); then
  `uv run pytest tests/unit -q`: 3478 passed; `uv run pytest tests/unit/evals -q`: 110 passed;
  `uv run ruff check app tests`: clean; `ruff format --check` on the 7 touched .py files: clean;
  `uv run mypy` on the 3 touched app files: no issues.
- Decisions: wording reuses `_ask_name_only_message` / `_ask_dni_only_message`; "Probar otro dato"
  still increments `not_found_retries` (escalation to handoff unchanged); free text at the chooser
  accepts a single valid piece (2+ word name or valid DNI), a malformed DNI repeats the chooser;
  incomplete checkpoints ask only for the missing piece. Eval `audit_followups.yaml` turn 4 now
  expects the chooser buttons (no renumbering; turn 5 free text still reaches the confirmation).

## Next step

Push / PR are the user's decision.
