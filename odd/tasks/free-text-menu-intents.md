# Free-text menu intents

## Objective

Every option the bot offers as a WhatsApp button or list row must also be reachable
by free text: the LLM classifies what the patient wrote and the graph answers exactly
as if the matching button id had been tapped. Stale workflow state must never hijack
a fresh request.

## Problem

Observed live (2026-09-23): "Hola buenas" → welcome list; "Quería agendar un turno" →
"confirmame o cancelá el turno usando los botones" (no proposal existed); tapping
Confirmar → "no me figura la propuesta que confirmaste".

Root causes (mapped, file:line on main 66103bb):

1. The new-conversation welcome is sent without invoking the graph
   (`app/application/messages/ingest_message.py:358-367`), so stale `stage` /
   `pending_action_id` from an earlier flow survive in the checkpoint
   (`app/infrastructure/agent/langgraph_agent_invoker.py:324-333`).
2. With an active stage, `resolve_interaction` discards the LLM classification and
   forwards `intent="appointment"` (`app/agent/nodes/resolve_interaction.py:301-307`);
   the `awaiting_confirmation` gate then asks to confirm any free text
   (`app/agent/nodes/appointment.py:1886-1918`), even when the pending action is gone.
3. Free-text parity gaps: "location" is not an LLM intent label
   (`app/infrastructure/llm/openai_compatible_llm_provider.py:40-46,71`) — only a
   hardcoded substring check (`app/agent/nodes/location.py:10-29`) reaches the
   "Cómo llegar" card; other phrasings get an LLM prose answer. `navigation_target="main"`
   does not take the same path as `MENU_MAIN_PAYLOAD` (`appointment.py:1863-1872`).

## Why

Patients write instead of tapping. Buttons and text must converge on one path per
option, so behavior is identical whichever the patient uses.

## Scope

- Normalize free text into the same canonical payload id at the single convergence
  point (`resolve_interaction`), reusing the existing button routing.
- Clear stale workflow state on a new-conversation welcome.
- A clearly different operation (create/cancel/reschedule/view) or a menu option asked
  mid-flow restarts/reroutes instead of being swallowed by the current stage.
- The confirmation gate never asks to confirm a proposal that does not exist.

## Constraints

- Strict TDD: observed RED before implementation, then GREEN, then REFACTOR.
- Runner: `uv run pytest` (source: session Strict TDD Mode). Also `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy app`.
- Known failures on base (not caused here): 4 tests in `test_gateway_dependency.py`,
  1 in `test_internal_eval_wiring.py`.
- Buttons keep working exactly as today; artifacts in English, patient copy unchanged.
- Delivery strategy: ask-on-risk.

## Tasks

- [x] T1 — New-conversation welcome clears stale `stage` / `pending_action_id`
  (reproduce with a RED test first; reuse `RotateWorkflowSessionUseCase` or the
  fresh-restart path). Route: delegated direct (writer trigger: 2+ files).
- [ ] T2 — Confirmation gate: when the pending action is missing/unresolvable, drop the
  stale stage and route by the classified intent instead of reminding to confirm.
  Mid-flow, a clearly different operation or menu option wins over the active stage.
  Route: delegated direct.
- [ ] T3 — Free-text → canonical payload parity for every menu option: add "location"
  to the LLM understanding labels/prompt and map it to `MENU_LOCATION_PAYLOAD`;
  `navigation_target="main"` behaves like `MENU_MAIN_PAYLOAD`; handoff and operations
  keep parity. One parity test per option (button vs text → same reply/node).
  Route: delegated direct.

## Acceptance criteria

- The screenshot scenario replays to the specialty list, not a confirmation reminder.
- For each menu option, a free-text equivalent produces the same node and reply as the
  button payload.
- Existing button tests stay green.

## Progress

- Branch `fix/free-text-menu-intents` from origin/main 66103bb.
- T1 done. Verified root cause: `is_new_conversation` is true only when
  `_resolve_or_create_conversation` finds no `Conversation` row for
  `ycloud-{phone}` (`ingest_message.py`) — and a brand-new row always starts
  at the SAME fixed `workflow_session_generation == 1`
  (`app/domain/entities/conversation.py:34`), so its checkpoint thread id
  (`f"{conversation_id}:session:1"`, computed in
  `langgraph_agent_invoker.py:244-245`) is fully deterministic. The
  new-conversation welcome branch (`ingest_message.py:241-262`, skip at
  `358-367`) never rotated the workflow session, so if this exact
  conversation id ever existed before (row deleted/recreated — e.g. a
  support reset) and left a pending action or checkpoint stage tied to that
  same generation 1, a brand-new incarnation's very next real agent turn
  would pick that stale state right back up — matching the screenshot
  (welcome on "Hola buenas", then straight into the confirmation gate on
  the next message). Confirmed the doc's original root-cause mapping was
  the correct path; no alternate path found.
  Fix: `ingest_message.py`'s existing inactivity-rotation block (guarded by
  `rotate_workflow.is_inactive(...)`, already reused by the lazy
  human-mode-timeout precedent) now also rotates when `is_new_conversation`
  is true, reusing `RotateWorkflowSessionUseCase` — bumps
  `workflow_session_generation` off its deterministic default and expires
  any pending action still parked at the old generation. Welcome-only,
  no-second-agent-reply behavior unchanged.
  RED: `test_new_conversation_welcome_rotates_workflow_session_and_expires_stale_pending_action`
  (`tests/unit/application/messages/test_ingest_message.py`) — failed with
  `AssertionError: assert 'pending' == 'expired'` before the fix.
  Verification: `uv run pytest -q` → 1567 passed, 82 skipped, 5 failed (the
  5 pre-declared known environmental failures only). `uv run ruff check .`
  → all checks passed. `uv run ruff format --check .` → 77 files (down from
  79 pre-existing on base; the 2 files this task touched are clean).
  `uv run mypy app` → no issues (320 files).
  Commits: 44f583e (code+tests), <doc commit to be added>.

## Next step

T2.
