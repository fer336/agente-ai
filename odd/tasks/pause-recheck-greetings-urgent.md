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
- [ ] T2 (A+D) Greeting shows the welcome menu again; FAQ menu only for programmed topics.
- [ ] T3 (B+C) Deterministic urgent-wording pre-check routing to `handoff`; empty list body check.
- [ ] T4 (F) Dataset expectation fixes, README/docs, scaffold lists consistent.

## Authorized scope
app/agent/**, app/application/messages/**, app/infrastructure/agent/**, app/infrastructure/llm/**,
app/domain/value_objects/**, evals/datasets/coverage.yaml, evals/assertions/custom.js,
evals/README.md, tests/**, this file.

## Route declaration
Single writer, inline (delegation not available to this agent); each task is one work-unit commit.

## Tests changed because they asserted old behavior
(none yet)

T1 note: wiring the gate needed one line in `app/api/dependencies/gateways.py` (outside the listed surfaces, required to inject `get_runtime_config_service().agent_may_respond`). The internal eval invoker stays ungated on purpose. No other direct sends exist under `app/agent` or `app/infrastructure/agent`. AgentRun status stays `completed` (no gated status exists); the skip is logged as `agent_gated_before_send`. A gate that raises keeps the reply (fail-open, logged).

## Verification
(filled per task)

## Not run
Nothing was run against the real Gemini model. The parent re-runs the 281-case promptfoo suite.
