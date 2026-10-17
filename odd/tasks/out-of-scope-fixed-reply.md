# Out-of-scope fixed reply

## Objective
When a patient asks for something the bot does not support (the "confused patient" branch of
`app/agent/nodes/fallback.py`), reply with ONE FIXED Spanish text (no LLM call for the text) and
THREE buttons: `📅 Agendar una cita`, `💬 Administración`, `📋 Menú principal`.

## Problem
The branch currently asks the LLM for the wording (backup text `_CONFUSED_PATIENT_MESSAGE`) and
shows only two buttons. The clinic wants a stable, approved wording and a way back to the menu.

## Approved wording (verbatim)
"Disculpame, con eso no te puedo ayudar por acá 🙏 Solo puedo guiarte con la información del menú principal.\nSi querés sacar un turno, tocá *Agendar una cita*. Y si necesitás otra cosa, escribile a *Administración* o volvé al *Menú*."

## Scope / constraints
- Payloads reuse existing constants: `OPERATION_CREATE_PAYLOAD`, `MENU_ADMIN_PAYLOAD`, `MENU_MAIN_PAYLOAD`. Routing is not changed.
- Titles <= 20 chars, max 3 reply buttons.
- Branch based on `origin/main` (pause-switch PR #250 not merged; not a base).
- Not pushed, no PR.

## Branches of `fallback.py` (what changes)
1. Location question (`asks_for_location`): unchanged.
2. `pending_answer` (the model already answered a genuine question): UNCHANGED, keeps the
   2-button `_CONFUSED_PATIENT_BUTTONS` (renamed `_ANSWERED_QUESTION_BUTTONS`), payment-text
   override and handoff-offer buttons intact. This is not an out-of-scope reply.
3. Welcome menu just shown (`_welcome_menu_was_just_shown`): UNCHANGED (LLM reminder + WELCOME_LIST).
4. Generic confused-patient branch (last one): CHANGED. No `generate_or_fallback` call; returns
   `OUT_OF_SCOPE_MESSAGE` and `_OUT_OF_SCOPE_BUTTONS` (3 buttons). `fallback_count` is still
   tracked in `collected_data`.
- Side effect: the `fallback` LLM intent is no longer requested by the node; the repeat-miss
  escalation instruction disappears (the fixed text already offers Administración every time).

## Tasks
- [x] T1 Tests first (RED), then fixed text + 3 buttons in the generic branch; update old tests. Route: inline (single file + its test, already understood).
- [x] T2 Promptfoo dataset `evals/datasets/out_of_scope.yaml`, registered in config and in the scaffold/replay tests; evals README section. Route: inline.

## Acceptance criteria
- Exact text match; exactly 3 buttons with the right ids/titles; no LLM text call on this path.
- `MENU_MAIN` payload still routes to the main menu (existing tests in `test_resolve_interaction.py` and `test_langgraph_agent_invoker.py`, plus a new assertion tying the button id to it).
- `uv run pytest tests/unit -q`, ruff check, ruff format --check, mypy app pass (3 known failures in `test_gateway_dependency.py` accepted).

## Progress / evidence
- T1 (inline): RED = new tests import `OUT_OF_SCOPE_MESSAGE` -> ImportError at collection of
  `tests/unit/agent/nodes/test_fallback_node.py`. GREEN: `fallback.py` generic branch returns the
  fixed text + 3 buttons; 21 passed. Removed LLM-wording tests of the generic branch (forwarding
  recent messages, instruction, escalation, attempts count) since that path no longer calls the LLM;
  added exact-text, 3-button, no-LLM and MENU_MAIN routing tests. `uv run pytest tests/unit -q`
  (gateway_dependency deselected): 3769 passed. ruff check/format and mypy app clean.

## Next step
Hand the branch to the user; push and PR are theirs.
