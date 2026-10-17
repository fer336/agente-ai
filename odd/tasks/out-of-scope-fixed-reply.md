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

- [x] T3 Free-text questions that are not a programmed capability never get an LLM-composed answer (fixed text + 3 buttons). Route: inline by the single writer (one behavior, 2 source files + tests).

## Acceptance criteria
- Exact text match; exactly 3 buttons with the right ids/titles; no LLM text call on this path.
- `MENU_MAIN` payload still routes to the main menu (existing tests in `test_resolve_interaction.py` and `test_langgraph_agent_invoker.py`, plus a new assertion tying the button id to it).
- `uv run pytest tests/unit -q`, ruff check, ruff format --check, mypy app pass (3 known failures in `test_gateway_dependency.py` accepted).

## Progress / evidence
- Commit T1: `375f78d` (feat(agent): reply to out-of-scope requests with a fixed text and three buttons).
- T1 (inline): RED = new tests import `OUT_OF_SCOPE_MESSAGE` -> ImportError at collection of
  `tests/unit/agent/nodes/test_fallback_node.py`. GREEN: `fallback.py` generic branch returns the
  fixed text + 3 buttons; 21 passed. Removed LLM-wording tests of the generic branch (forwarding
  recent messages, instruction, escalation, attempts count) since that path no longer calls the LLM;
  added exact-text, 3-button, no-LLM and MENU_MAIN routing tests. `uv run pytest tests/unit -q`
  (gateway_dependency deselected): 3769 passed. ruff check/format and mypy app clean.
- T2 (inline): added `evals/datasets/out_of_scope.yaml` (10 out-of-scope cases + 3 in-scope
  controls, all deterministic, `requires_real_llm: false`), helpers `isOutOfScopeReply` /
  `isNotOutOfScopeReply` in `custom.js`, registered in `promptfooconfig.yaml` and the two eval
  test lists, README section. A first draft of the "emergency" case (heavy bleeding) is routed to
  human handoff by design, so it was reworded to a mild-pain worry question. Evals were NOT run
  (no network/keys); structure and deterministic replay verified with `uv run pytest tests/unit/evals`
  (113 passed). Full `uv run pytest tests/unit -q`: 3809 passed, 3 failed (known pre-existing
  `test_gateway_dependency.py`). ruff check, ruff format --check, mypy app clean.
- Commit T2: see git log (`test(evals): add out-of-scope dataset`).

## T3 map: how a free-text message became `pending_answer` (before the change)
- Prompt/schema: `DEFAULT_UNDERSTAND_PROMPT` and its "answer" field (`app/infrastructure/llm/openai_compatible_llm_provider.py:101-178`, "answer" at :149); `UnderstandingResult.answer`/`handoff_offer` (`app/domain/repositories/llm_provider.py`). Fake: `app/infrastructure/llm/fake_llm_provider.py:274-292` (payment keywords return intent=question + answer).
- Router: `_carried_understanding` stores `result.answer` as `pending_answer` and `handoff_offer` as `HANDOFF_OFFER_FLAG_KEY` (`app/agent/nodes/resolve_interaction.py:272-292`); `_ROUTABLE_INTENTS`/`_INFORMATION_INTENTS` include `question` (:155, :243).
- Graph: intent `question` -> `QUESTION_NODE` (`app/agent/graph.py:130`); any other unrouted intent -> `FALLBACK_NODE` (:140).
- Consumers: `question.py` (old: off-topic regex, payment override, `guard_free_text_answer`, LLM "question_unknown_answer") and the `pending_answer` branch of `fallback.py` (old :101-135, payment override + `_ANSWERED_QUESTION_BUTTONS`).

## T3 change
- `app/agent/nodes/question.py`: rewritten. Never delivers the model answer or calls the LLM. Payment wording (in the user message or in the dropped model answer) -> `PAYMENT_ADMIN_STATIC_MESSAGE` + handoff offer buttons (unchanged behavior); everything else -> `OUT_OF_SCOPE_MESSAGE` + 3 buttons. `stage` and other `collected_data` are kept so an appointment resumes. `llm_provider` kept only for the factory signature.
- `app/agent/nodes/fallback.py`: the `pending_answer` branch no longer delivers the answer; it is dropped and the turn continues to the existing branches (welcome reminder via LLM, else fixed text). Payment wording still gets the fixed Administración redirect. `_OUT_OF_SCOPE_BUTTONS` renamed public `OUT_OF_SCOPE_BUTTONS` (reused by `question.py`); `_ANSWERED_QUESTION_BUTTONS` removed.
- Deliberately left: understand prompt and structured-output schema (still asks for `answer`; it is simply ignored, so no schema or admin-prompt migration); `resolve_interaction` still carries `pending_answer` (used only as a payment signal) and `HANDOFF_OFFER_FLAG_KEY`; location, faq_topic, payment_admin, handoff, welcome menu and reminder nodes untouched. Unused-by-these-nodes helpers (`guard_free_text_answer`, `answer_offers_handoff`) remain for other callers.
- Behavior note: previously the "horarios de atención / extracciones" style questions were answered by the model; they now get the fixed text (no clinic facts are programmed for them).

## T3 tests
- RED: new/updated node tests fail against the old app code (24 failed with the app changes stashed), GREEN after.
- Tests that asserted the OLD free-answer behavior and were rewritten: `tests/unit/agent/nodes/test_question_node.py` (whole file), `test_fallback_node.py` (pending_answer delivery/greeting/handoff-offer tests), `test_no_premature_action_claims.py` (question/fallback claim + diagnosis tests), `tests/unit/agent/test_handoff_offer_flag.py` (delivery + audit replay + guard-replaced tests), `tests/unit/infrastructure/agent/test_langgraph_agent_invoker.py::test_a_handoff_offer_has_buttons_and_a_free_text_yes_hands_over_to_administration` (now drives the payment-redirect offer).
- New: parametrized node test (diagnosis/price/medication/joke/insult/hours/empty answer -> fixed text + exactly 3 buttons, LLM text generation forbidden) and a full-graph invoker test where the fake LLM returns a free-form answer for a question and the sent message is still `OUT_OF_SCOPE_MESSAGE` with the three buttons.
- Evals: `evals/datasets/out_of_scope.yaml` case "pide hablar con el doctor ya" (routed to the booking flow by design) moved to the in-scope controls asserting `isNotOutOfScopeReply` only; README text updated. `custom.js` unchanged (the fixed text did not change).
- Commits: `a998250` (feat(agent): answer free questions with the fixed out-of-scope text instead of the model's reply), `c39e56e` (test(evals): move the doctor-now case to the in-scope controls).

## T3 verification and caveats
- `uv run pytest tests/unit -q` (gateway_dependency deselected): 3771 passed, 4 failed, all `tests/unit/evals/test_dataset_replay.py` parametrized cases (audio, flows_view_appointment, location, out_of_scope). On the base commit the same file also fails 3 of its cases in a full-file run here ("attached to a different loop" / handled_error in the replay harness, environmental flakiness); every one of those four cases passes when run alone with `-k` on this branch.
- ruff check, ruff format --check, mypy app: clean.
- NOT verified: no real-LLM run. The real model may still return non-`question` intents for chit-chat (those reach `fallback`, now also fixed text) or route some topics to `handoff`/`appointment`; the parent must run the promptfoo suite against Gemini.

## Next step
Hand the branch to the user; push and PR are theirs.
