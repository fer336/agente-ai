# Pause re-check, greetings, urgent wording, FAQ scope

## Objective
Fix the real-bot problems found by the 281-case coverage run (257 passed, 24 failed) and correct
the dataset expectations that were wrong. Branch `fix/pause-recheck-greetings-urgent` (from
`origin/main`, which has the pause switch #250 and the fixed out-of-scope reply #251), plus the
local coverage-dataset commits cherry-picked from the old branch. Not pushed, no PR.

## Evidence (real Gemini promptfoo run)
- A: greetings get the out-of-scope text instead of the welcome menu.
- B: "No puedo respirar bien y me duele la muela" produced the specialties list, not a handoff.
- C: '🦷' returns a list with an empty `reply_text`.
- D: off-topic questions reach the FAQ topic menu instead of the fixed out-of-scope text.
- E: an in-flight turn keeps running and replies after the admin paused the agent.
- F: some dataset expectations were wrong, not the bot.

## Tasks
- [x] T1 (E) Re-check the pause/contact gate right before the outbound send in `LangGraphAgentInvoker`; nothing sent when gated.
- [x] T2 (A+D) Greeting shows the welcome menu again; FAQ menu only for programmed topics.
- [x] T3 (B+C) Deterministic urgent-wording pre-check routing to `handoff`; empty list body check.
- [x] T4 (F) Dataset expectation fixes, README/docs, scaffold lists consistent.

## Authorized scope
app/agent/**, app/application/messages/**, app/infrastructure/agent/**, app/infrastructure/llm/**,
app/domain/value_objects/**, evals/datasets/coverage.yaml, evals/assertions/custom.js,
evals/README.md, tests/**, this file.

## Route declaration
Single writer, inline (delegation not available to this agent); each task is one work-unit commit.

## Tests changed because they asserted old behavior
(none yet)

T1 note: wiring the gate needed one line in `app/api/dependencies/gateways.py` (outside the listed surfaces, required to inject `get_runtime_config_service().agent_may_respond`). The internal eval invoker stays ungated on purpose. No other direct sends exist under `app/agent` or `app/infrastructure/agent`. AgentRun status stays `completed` (no gated status exists); the skip is logged as `agent_gated_before_send`. A gate that raises keeps the reply (fail-open, logged).

T2 changes: `app/agent/greetings.py` (strict whole-message greeting detector), `app/agent/faq_scope.py` (programmed topic / price / generic-info check). `resolve_interaction` sends an idle greeting to `unknown` (before the LLM); the fallback node answers a greeting with `WELCOME_TEXT` + `WELCOME_LIST` (same constants as the welcome-after-welcome branch, not counted as a miss). An LLM `faq_topic` without a valid topic id and without a programmed topic/price/info wording is demoted to `question` (fixed out-of-scope reply). Price questions about unprogrammed treatments (implante, corona) still reach the FAQ menu on purpose. Tests updated because they used a greeting as a generic miss: `test_fallback_node.py::test_without_a_recent_welcome_menu_the_out_of_scope_text_is_used`, `test_handoff_offer_flag.py::test_a_model_answer_that_offers_a_handoff_is_replaced_by_the_fixed_text`, `test_resolve_interaction.py::test_understand_is_told_whether_the_conversation_already_started`, `test_langgraph_agent_invoker.py::test_handle_records_an_agent_run_with_failed_status_when_a_node_raises`.

T3 changes (B): `automatic_handoff._is_emergency` extends the single deterministic pre-check already used by `resolve_interaction` (it runs before the LLM, in every stage; the existing `sangr\w*` rule already covered "sangra mucho"/"sangrado que no para", the fake LLM never routed it). New: no puedo/me cuesta/dificultad para respirar, me falta el aire, desmayo, traumatismo, golpe fuerte en la cabeza, dolor insoportable, swollen face/neck + fever, a blow + tooth lost/moved. Negations ("sin desmayos", "no tengo dolor insoportable") do not fire. The new unit cases were written together with the code (the sangrado ones passed before it); the genuinely new wording is covered by `tests/unit/agent/test_automatic_handoff.py`.
T3 (C): the list body CAN be empty at send time (`specialties` returned `response_text=None` and the invoker passes `""`; YCloud rejects a list with an empty body). Fixed at both layers: the specialties node now sets `CHOOSE_SPECIALTY_PROMPT` (new public constant in `paginated_list.py`, same wording as the appointment flow) and the back-to-menu list sends `WELCOME_TEXT`; `SendReplyUseCase` falls back to "Elegí una opción de la lista:" for any list with a blank body.

T4 changes (F): `custom.js` gets `isWelcomeMenuReply` and `replyIsHealthy` also accepts `reply_kind: list` with non-empty `list_rows` (scaffold helper list, helper tests and README updated). Dataset: greetings (cap-082..089, fmt-004, chat-024/025) expect the welcome menu; urgent cases sec-027..031 expect node `handoff` and status `handoff`; sec-011/013/014 expect the fixed out-of-scope reply; sec-012/026 expect the appointment node and no decoy values. The off-topic cases (oos-031/040/047 and the photo-diagnosis one) already expected the out-of-scope text and now pass by the T2 routing change.

## Verification
- `uv run pytest tests/unit -q --deselect tests/unit/evals/test_dataset_replay.py`: 3957 passed, 3 failed (the pre-existing `test_gateway_dependency.py` ones).
- `test_dataset_replay.py` per case with `-k "current_flow and <dataset>"` for audio, flows_view_appointment, location, out_of_scope: each passed (a full run fails with event-loop errors, flaky also on main).
- `uv run ruff check app tests`: all checks passed. `uv run ruff format --check app tests`: 690 files already formatted. `uv run mypy app`: no issues in 373 files.

## Not run
Nothing was run against the real Gemini model. The parent re-runs the 281-case promptfoo suite.
