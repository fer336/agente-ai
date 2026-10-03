# Audit fixes: topic paraphrases and premature cancellation wording

## Objective

Fix the real agent gaps found by the 2026-10-03 production audit (v0.50.1, real LLM, judge
cx/gpt-5.6-terra via 9router: 176/181 passed, 5 failed).

## Problem

1. "¿Cuánto me sale aclararme los dientes?" (blanqueamiento paraphrase) got the 5-topic list
   instead of the blanqueamiento answer: the LLM labels it `faq_topic` but the keyword matcher
   finds no topic, so the router falls back to the list.
2. "¿Atienden pacientes particulares?" got the same list; the right answer is the consulta
   particular text. The dataset case expected handoff buttons (stale expectation).
3. "Cancelame el turno, sí, hacelo" (typed at the cancel confirmation stage) got an LLM-written
   reply saying "ahí lo cancelo entonces" while showing the confirmation buttons: it reads as if
   the cancellation had been done, but nothing was cancelled yet.

Not in scope (judged strictness, no safety issue): the third-party data request and the chained
injection cases (the agent leaks nothing and does not obey).

## Scope

- T1: topic recognition. (a) Add accent-folded keywords/phrases: blanqueamiento ("aclarar",
  "aclararme", "aclarame", "aclarar los dientes", "dientes blancos", "dientes mas blancos",
  "blanquearme"); consulta particular ("pacientes particulares", "atienden particulares",
  "atienden pacientes particulares", "atienden particular", "sin obra social"). Keep the guard
  that a booking phrase ("turno para ...") still goes to booking and the generic word "consulta"
  alone is not a topic. (b) Let `understand()` return which of the five topics the patient means:
  an optional `faq_topic_id` in its JSON (validated against `CLINIC_TOPICS` ids, anything else
  ignored), documented in the understand prompt, parsed, carried through `UnderstandingResult`
  and used by the router when the intent is `faq_topic` and no keyword matched; no id -> the list
  as today. The fake LLM keeps its keyword behavior.
- T2: premature action wording. Find where the LLM-written reply at the cancel-confirmation stage
  comes from and why `claims_executed_action` did not catch "ahí lo cancelo entonces"; extend the
  guard (present/future affirmative claims such as "lo cancelo", "ahí lo cancelo", "te lo
  cancelo", "lo agendo", "lo reprogramo", "ya lo hago", also for agendar/reprogramar) and/or the
  instruction of that reply so it only asks to use the buttons; fall back to the static text.

## Constraints

- Branch `fix/audit-topic-paraphrases` from origin/main (ba18fdb, v0.50.1), worktree
  `../agente-ai-worktrees/audit-fixes`.
- Strict TDD. Runner: `uv run pytest`; also `uv run ruff check .`, `uv run mypy app/`,
  `uv run ruff format --check <changed files>`.
- Known environmental failures: `tests/integration/test_redis_debounce_lock.py` (3).
- English artifacts, Spanish patient copy, no AI attribution in commits.
- Delivery: `docs/pr-release-workflow.md`, `fix(...)` title (patch release).

## Tasks

- [x] T1 — topic keywords and `faq_topic_id` from `understand()`. Commit 839c6f8.
- [x] T2 — no premature "lo cancelo" wording. Commit 82a03ef.

## Acceptance criteria

- "¿Cuánto me sale aclararme los dientes?" and "¿Atienden pacientes particulares?" answer with the
  blanqueamiento and the consulta particular texts.
- A reply at a confirmation stage never says it already or will immediately do the action.
- The dataset cases are updated to the new behavior and replay green.

## Progress

- Worktree created (2026-10-03).
- T1 done (839c6f8). RED observed: 14 matcher cases (test_clinic_topics.py), 16 parser/prompt/router
  tests (faq_topic_id) before implementing; GREEN after. Decisions: bare "aclarar"/"aclarame" are NOT
  keywords (everyday verbs: "aclarame una duda" would answer the blanqueamiento); only teeth
  phrasings ("aclarar/aclararme/aclarame los dientes", "aclarar dientes", ...). The consulta
  particular phrases and "sin obra social" are `weak_keywords`, consulted only when no regular
  keyword matched, so "brackets/limpieza sin obra social" keep their topic. Dataset: new
  deterministic cases in clinic_topics.yaml; flows.yaml "Oferta de handoff ... turn 2" now expects
  the consulta particular topic (real LLM: it is typed inside the first-visit data stage, where the
  keyword pre-check is skipped by design). tests/unit/agent/test_handoff_offer_flag.py replay message
  changed to "aceptan particulares" (the old wording is now a topic keyword).
- T2 done (82a03ef). Cause: the cancel-confirmation free-text reminder (appointment.py, via
  generate_or_fallback "confirmation_reminder") was only guarded by claims_executed_action, whose
  patterns required "te lo ..." so "ahí lo cancelo entonces" passed. RED observed: 26 tests. Guard
  extended (lo/la + present, "cancelo el turno", "procedo a ...", "ya lo hago", "lo hago ya/ahora",
  "listo, lo hago"); the four confirmation_reminder contexts now carry a mandatory "instruccion";
  action_executed=True still skips the guard. Dataset case 'Cancelar sin confirmación previa'
  unchanged (rubric already covers it).

## Next step

Open the PR per docs/pr-release-workflow.md (not pushed).
