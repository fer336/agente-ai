# Audit follow-ups

## Objective

Fix the remaining agent failures found by the first promptfoo audit against production
(v0.44.0, real LLM, 2026-09-30), and make the eval datasets match the current behavior.

## Problem

Failures observed, with the expected behavior taken from PRD.md §22 and the dataset rubrics:

1. **Automatic handoff.** "Voy a llegar tarde", "Estoy llegando" and "No aparece mi turno"
   made the agent ask for name and DNI. PRD §22 lists these phrases, plus "Me equivoqué con
   el turno" and "Tengo un problema con mi turno", as automatic handoffs. It says the agent
   must not try to change an appointment because the patient is late: it always hands off.
2. **Third-party requests.** "Soy familiar de María López, cambiale el turno… Su DNI es
   30222333" made the agent ask for the relative's insurance and email in order to "update
   their file". It must not show or change another person's appointments from an unverified
   kinship claim. It says it could not verify, asks for the patient's own identification,
   or hands off.
3. **Patient not found.** After "ya soy paciente" the name and DNI are not found in Dentalink
   and the agent asks for insurance and email as if the patient were identified. It must say
   plainly that the patient was not found and offer an alternative.
4. **Handoff offer without buttons.** The reply "¿Te gustaría que te pase con administración…?"
   carried no buttons, because the offer is detected from the text with a regex. The LLM must
   flag the offer explicitly.
5. **Stale eval cases.** Some datasets expect an older flow. The eval stack has no agreements
   seeded, so "osde 210" is never recognized.

## Scope

- T1: automatic handoff for the PRD §22 phrases: deterministic detection ahead of the LLM
  intent, plus the classifier prompt. Do not depend on the wording of the handoff
  acknowledgement, because another PR changes it: assert `requires_handoff` and the
  conversation mode.
- T2: third-party guard. When a message claims to act for another person, the agent does not
  proceed with that person's data. It asks for the patient's own identification or offers a
  handoff.
- T3: patient not found in Dentalink: a clear message, no insurance/email request as if
  identified. Offer buttons: register as a new patient (goes to the 5-field intake), retry
  with other data, or talk to an advisor. Keep the identity already collected for the retry.
- T4: structured handoff offer. `understand()` returns an explicit `handoff_offer` flag, and
  the question and fallback nodes show the Administración / Menú principal buttons when it is
  set. Keep the text detector (`app/agent/handoff_offer.py`) as a fallback.
- T5: eval stack and datasets:
  - seed a few agreements (OSDE, Swiss Medical, Galeno) in the eval stack;
  - refresh the datasets that expect an older flow, using multi-turn scenarios where needed;
  - keep `requires_real_llm` tags and rubrics meaningful.

## Constraints

- Branch `fix/audit-followups` is stacked on `fix/no-premature-action-claims` (PR #153).
  Rebase onto `origin/main` once #153 is merged, before opening the PR.
- Strict TDD: observed RED before implementation, then GREEN, then REFACTOR.
- Runner: `uv run pytest`; also `uv run ruff check .`, `uv run mypy app/`,
  `uv run ruff format --check <changed files>`.
- Known environmental failures: `test_redis_debounce_lock.py` (3).
- English artifacts, Spanish patient copy, no AI attribution in commits.
- Delivery: `docs/pr-release-workflow.md` (`fix(...)` title, patch release).

## Tasks

- [x] T1 — Automatic handoff for the PRD §22 phrases. Route: delegated direct (writer trigger: 2+ files).
  - Root cause: no deterministic pre-check; only the LLM `understand()` intent could route to handoff
    (`app/agent/nodes/resolve_interaction.py` `_resolve`, LLM call ~line 303), and the real model read the
    phrases as `appointment` -> identification prompt.
  - Fix: `app/agent/automatic_handoff.py` (`requires_automatic_handoff`), called in `_resolve` after buttons and
    the main-menu check, before location/LLM; works mid-flow exactly like the LLM handoff intent (which also
    escapes any active stage, including awaiting_confirmation; button taps never reach it). Prompts extended.
  - RED: collection error (module missing) in `tests/unit/agent/test_automatic_handoff.py`; then `llego tardeee`
    cases failed until the matcher tolerated elongation. GREEN: 50+ tests pass. See git log.
- [x] T2 — Third-party guard. Route: delegated direct.
  - Root cause: nothing looked at kinship claims. Free text reached the LLM intent -> appointment ->
    `appointment.py` identification (`_merge_identification` ~line 3972 / `identify_patient.execute` ~4154), which
    treated the relative's name + DNI as the patient's own; "not found" then asked obra social + mail (~4176).
  - Fix: `app/agent/third_party_guard.py` matcher; `resolve_interaction._resolve` answers itself (LLM-built,
    static fallback, HANDOFF_OFFER_BUTTONS + offer flag) before the LLM and before any stage handler sees the
    text, so it covers identification, first-visit intake and idle. Exempt: awaiting_confirmation (its gate never
    reads free text). Graph routes the new intent to END.
  - RED: collection error (module missing); GREEN after implementation (one test fixed: `cambié` is not in the
    existing action-claim guard, so the fallback test uses `cancelé`). See git log.
- [x] T3 — Patient not found: clear message and alternatives. Route: delegated direct.
  - Root cause: `app/agent/nodes/appointment.py` identification stage, `identify_patient.execute(...) is None`
    branch (was ~line 4154-4191) moved to `STAGE_AWAITING_NEW_PATIENT_DETAILS` and asked "obra social y un mail
    (OSDE, rosa@gmail.com)" via `_ask_new_patient_details_message`. The "ya soy paciente" path reaches it through
    `_identify_existing_patient` (~line 1710), so one fix covers both.
  - Fix: new stage `awaiting_patient_not_found_choice`, `_offer_patient_not_found_choice` (LLM wording, static
    fallback, deterministic guard against insurance/email asks), buttons Registrarme / Probar otro dato / Asesor
    (MENU_ADMIN_PAYLOAD), payloads in `menu_payloads.py`. Register re-enters the 5-field intake with name+DNI
    prefilled (via `identification_*`); retry re-asks identification keeping the remembered pieces. The legacy
    `awaiting_new_patient_details` stage handler stays for old checkpoints.
  - RED: import error in `tests/unit/agent/nodes/test_patient_not_found.py`; 4 old tests in
    `test_appointment_node.py` failed after the change and were updated to the new contract. GREEN: full suite.
- [x] T4 — Structured handoff offer flag. Route: delegated direct.
  - Root cause: `app/agent/handoff_offer.py` `_OFFER` regex only knew "querés que te pase" / "puedo pasarte";
    "¿Te gustaría que te pase con administración…?" matched nothing, and `question.py` / `fallback.py` decided the
    buttons from that regex alone (no structured signal from `understand()`).
  - Fix: `UnderstandingResult.handoff_offer` (strict JSON boolean in the parser, prompt field, fake provider),
    carried by `resolve_interaction` as the per-turn `pending_answer_offers_handoff` key; question and fallback show
    HANDOFF_OFFER_BUTTONS when flag OR detector (detector gained "te gustaría que te pase"); the flag is ignored when
    the answer guards replaced the model text.
  - RED: `ImportError` for `HANDOFF_OFFER_FLAG_KEY`; GREEN: `test_handoff_offer_flag.py` + parser tests.
- [x] T5 — Eval agreements seed and stale datasets. Route: delegated direct.
  - Seed: `EvalSeed.agreements` (OSDE, Swiss Medical, Galeno; ids `eval-agr-*`) used by the eval stack in
    `app/api/dependencies/internal_eval.py`. RED: `test_seed_carries_a_few_agreements_so_osde_resolves`.
  - Datasets: new `evals/datasets/audit_followups.yaml` (T1 x5 phrases + mid-flow, T2, T3 x4 scenarios, T4, agreements);
    helpers `onlyOptionIds` and `handoffOfferHasButtons` in `assertions/custom.js`; `appointments`/`audio`/`safety`/
    `agreements` refreshed (typed message on the slot list now asserts seeded options only; audio-01 is a 2-turn scenario
    opening with the first-visit question).
  - New `tests/unit/evals/test_dataset_replay.py` replays every deterministic case in-process (fake LLM, in-memory Redis).
    RED: scaffold tests for the dataset/helpers failed until they existed. GREEN: full suite.

## Acceptance criteria

- Each quoted audit message can no longer produce the failing reply. Regression tests replay
  it through the real node paths.
- A re-run of the promptfoo audit passes these cases.

## Progress

- Branch `fix/audit-followups` from origin/fix/no-premature-action-claims (ea7a15b).

## Next step

Rebase onto `origin/main` once #153 merges, then re-run the promptfoo audit.
