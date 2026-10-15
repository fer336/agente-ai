# Structured output for `understand`

Branch: `feat/llm-structured-output-for-understand` (based on `origin/main`, release `v0.60.4`).

## Objective
Make `understand` return the exact JSON shape the router needs by asking the model for a JSON schema (`response_format`), instead of hoping it obeys "return only a JSON" in the prompt.

## Problem
With Gemini (`gemini-3.1-flash-lite`, official Google endpoint) `understand` answers in prose or with the wrong keys, so the router cannot read the intent. The measured failure (10 requests per variant, the real `understand` request body, 2026-10-15):

| Variant | Valid understanding JSON | Latency |
|---|---|---|
| prompt as it is today | 0/10 (prose) | 0.95 s |
| reminder repeated last | 0/10 (`{"answer": ...}` without `intent`) | 0.88 s |
| `response_format: json_object` | 0/10 (invented keys `mensaje`, `accion`) | 0.93 s |
| `response_format: json_schema` (strict, all fields required) | 10/10 | 1.07 s |

## Why
Prompt-only formatting is not reliable with small models. A schema constrains the output at generation time. The same failure was seen in production logs (invalid JSON twice, then the guard added in a separate branch).

## Scope
- `OpenAICompatibleLLMClient.chat_completion` accepts an optional `response_format` and sends it only when given.
- `OpenAICompatibleLLMProvider.understand` sends the understanding JSON schema when structured output is enabled; `classify_intent`, `extract_information` and `generate_response` are unchanged.
- New setting `llm_structured_output` (env `LLM_STRUCTURED_OUTPUT`), default off, wired in `app/api/dependencies/gateways.py`.
- The schema is derived from `_UNDERSTANDING_LABELS` so labels cannot drift.

## Out of scope
- Schemas for `extract_information` (its fields vary per call) and `classify_intent`.
- The router guard for a failing `understand` (branch `fix/understand-fallback-on-llm-failure`) and the fixed-text PR (#242).
- Gateways that may reject `response_format` (9Router, OpenRouter models): not measured. That is why the setting defaults to off.

## Constraints
- English artifacts; test first (RED then GREEN).
- Default behavior must not change for anyone who does not set the variable.
- Push, PR and merge are the user's decisions.

## Route declaration
Inline: one non-trivial source file (`openai_compatible_llm_provider.py`); the client, settings and gateway edits are one-line plumbing. Delegation not triggered.

## Tasks
- [x] S1 Client sends `response_format` only when given. Evidence: new client test RED then GREEN.
- [x] S2 Provider builds the schema from `_UNDERSTANDING_LABELS` and sends it from `understand` only when enabled, on the first call and on the retry. Evidence: 4 provider tests RED then GREEN (off by default, strict schema, retry keeps it, only `understand` uses it).
- [x] S3 Setting `llm_structured_output` and wiring. Evidence: 2 settings tests RED then GREEN; wiring in `gateways.py`.
- [ ] S4 Verify against the real endpoint with the user's probe (`schema` variant) and record the result.

## Acceptance criteria
- With the setting off, requests are byte-identical to today.
- With it on, only `understand` carries `response_format` of type `json_schema`, strict, every property required, `intent` limited to the known labels.
- `tests/unit` green except the 3 known failures in `tests/unit/api/dependencies/test_gateway_dependency.py`.

## Progress
S1-S3 done. S4 (real endpoint, production setting) pending the user.

## Verification evidence
Probe results above (user-run, `probe.py` with `VARIANT=schema`). Unit: `uv run pytest tests/unit -q` 3658 passed, 3 known failures in `test_gateway_dependency.py`; `uv run mypy app` and `uv run ruff check app tests` clean.

## Next step
S4: after merge and release, set `LLM_STRUCTURED_OUTPUT=true` in the secret (Google official endpoint only), redeploy, and watch `invalid_llm_output` in the admin errors page.
