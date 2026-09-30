# Permanent eval audits

## Objective

Keep the eval endpoint enabled in production for future audits, so that an audit takes one
command and the endpoint stays safe while it is always on.

## Context

- The first production audit ran on 2026-09-30, against v0.44.0 with the real LLM and the
  `anthropic/claude-haiku-4.5` grader through OpenRouter.
- The user decided to keep `INTERNAL_EVAL_ENABLED=true` and `INTERNAL_EVAL_REAL_LLM=true` in
  production.
- The production secret `agente_ai_backend_env` already carries both flags. The user
  recreated it.
- The stack still points at the temporary `agente_ai_backend_env_eval`, which was created
  for the audit window.
- The agent's LLM is OpenRouter (`LLM_API_URL`, key `LLM_API_KEY`), not the host's 9Router.

## Scope

- T1: dataset format and grader config fixed during the first audit (cherry-picked):
  - datasets are top-level lists;
  - the `llm-rubric` grader is read from `EVAL_GRADER_MODEL`, `EVAL_GRADER_BASE_URL` and
    `EVAL_GRADER_API_KEY`.
- T2: restrict `POST /internal/eval/chat` to the `ADMIN_TECHNICAL` role. With the endpoint
  permanently enabled, any other role must get 403.
- T3: add `evals/run-audit.sh`, a one-command audit that:
  - runs against production by default, with the base URL overridable;
  - logs in with a silent password prompt, so the password never lands in argv or history;
  - reads the grader key from the running backend's secret file without printing it;
  - defaults the grader to OpenRouter `anthropic/claude-haiku-4.5`, overridable by env;
  - writes a run-scoped `EVAL_RUN_ID` and JSON results;
  - can optionally open the promptfoo UI bound to 127.0.0.1 only, through a preload
    (`promptfoo view` binds 0.0.0.0 by default);
  - never enables anything, never writes secrets to disk beyond a chmod-600 cookie jar,
    and deletes that jar at the end.
- T4: the stack uses `agente_ai_backend_env` again (remove the temporary `name:`), and the
  README documents the always-on posture:
  - cost only when an admin runs an audit;
  - `ADMIN_TECHNICAL` only;
  - how to turn it off;
  - removing `agente_ai_backend_env_eval` after the release deploys.

## Constraints

- Strict TDD for app code; runner `uv run pytest`; also `uv run ruff check .`,
  `uv run mypy app/`, `uv run ruff format --check <changed files>`; `shellcheck` on the
  script if it is available.
- Known environmental failures: `test_redis_debounce_lock.py` (3).
- Do not run the script, docker, servers or promptfoo while implementing. No AI
  attribution in commits.
- Delivery: `docs/pr-release-workflow.md` (a `feat(...)` title triggers a minor release).

## Tasks

- [x] T1 — Dataset format and grader config (cherry-picked from the local
  `fix/promptfoo-dataset-format`: 2b23941 and 787d9ae). Route: direct inline.
- [x] T2 — Eval endpoint restricted to `ADMIN_TECHNICAL`. Route: delegated direct.
  RED: 2 new 403 tests (ADMIN_CLINIC, READ_ONLY) got 200; GREEN after `require_role(ADMIN_TECHNICAL)`.
  Commit: 587aa92
- [x] T3 — `evals/run-audit.sh`. Route: delegated direct.
  Evidence: `bash -n` ok, static tests pass, shellcheck not installed. Commit: see git log (`feat(evals): add a one-command production audit script`).
- [ ] T4 — Stack back on `agente_ai_backend_env`, plus always-on docs. Route: delegated direct.

## Progress

- Branch `feat/permanent-eval-audits` from origin/main eae7f7a (v0.44.0), with T1
  cherry-picked as 13810f0 and 571dbaa.

## Next step

T4.
