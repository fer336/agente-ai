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
- [x] T2 — Confirmation gate: when the pending action is missing/unresolvable, drop the
  stale stage and route by the classified intent instead of reminding to confirm.
  Mid-flow, a clearly different operation or menu option wins over the active stage.
  Route: delegated direct.
- [x] T2b — Review follow-ups on T2 (review-c980054b8c626f90, approved, advisory):
  Confirmar/Cancelar tap or free-text decline with no pending action must recover
  instead of looping on the reminder (R3-button-tap-without-pending-id-reminds, in the
  acceptance criteria "never ask to confirm a proposal that does not exist"); test a
  pending-action row that exists but is not `pending` (R3-expired-row-branch-untested);
  guard the new repository lookup (R3-new-db-lookup-unguarded); expire the live
  proposal when the patient switches operation (R3-switch-leaves-live-proposal-pending).
  Route: delegated direct.
- [x] T3 — Free-text → canonical payload parity for every menu option: add "location"
  to the LLM understanding labels/prompt and map it to `MENU_LOCATION_PAYLOAD`;
  `navigation_target="main"` behaves like `MENU_MAIN_PAYLOAD`; handoff and operations
  keep parity. One parity test per option (button vs text → same reply/node).
  Route: delegated direct.

- [x] T4 — Review follow-ups on the full branch (review-fc1d81209235acfb, approved,
  advisory): a recreated conversation must start on a workflow generation no prior
  incarnation used (R3-new-conversation-rotation-can-collide-with-prior-incarnation-generation);
  guard the operation-switch reject against repository/provider errors
  (R3-operation-switch-reject-unguarded); keep the fake provider's `classify_intent`
  labels aligned with the real provider (R3-fake-classify-intent-diverges-from-real-labels).
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
  Commits: 44f583e (code+tests), d50ed70 (docs).

- T2 done. Residual gap from T1: `is_new_conversation` only rotates the
  workflow session for a genuinely BRAND NEW `Conversation` row — a
  conversation whose row already existed (e.g. a mid-flow abandon, or any
  path that never re-triggers the welcome) never rotates, so a stale
  `STAGE_AWAITING_CONFIRMATION` with a `pending_action_id` that no longer
  resolves to a `pending` row (expired, confirmed/rejected elsewhere, or
  simply gone) can still be live at generation 2+ regardless of T1's fix.
  T2 makes the confirmation gate self-healing against that residual case
  directly, independent of how the staleness got there: it no longer
  trusts `pending_action_id`'s mere presence, it resolves it
  (`PendingActionRepository.get_by_id`, `status == "pending"`) before ever
  reminding.
  Fix (`app/agent/nodes/appointment.py`, `STAGE_AWAITING_CONFIRMATION`
  free-text branch, ~1898-1962): when `button_payload is None`, resolve
  the pending action; if it isn't a usable `pending` row, OR the LLM's
  `operation_mention` (already carried into `collected_data` by
  `resolve_interaction.py`, unchanged) names a DIFFERENT operation than
  `collected_data["operation"]`, drop `stage`/`pending_action_id` and let
  the turn fall through the same `if stage == ...` dispatch chain a real
  `MENU_MAIN_PAYLOAD`/`_MAIN_MENU_PAYLOADS` tap already uses below (one
  path per operation, reusing `_offer_specialties`/`_begin_identification`/
  the operation-menu fallback — no new routing). The REJECT/CONFIRM/
  unrecognized-button branches (~1962-2350) were converted from three
  independent `if`s with an implicit fallthrough catch-all into
  `if/elif/elif/else`, since `state["button_payload"]` is never mutated
  (its own documented contract) — only the local `button_payload`/`stage`
  variables are, so the catch-all must no longer fire when the free-text
  branch chose to fall through instead of returning. Extended the
  existing `returned_to_main_menu` -> `pending_action_id: None` clearing
  (already done for CREATE, ~3574-3585) to the reschedule/cancel/view
  identification branch and the final operation-menu fallback too, for
  the same reason the existing comment there gives.
  Design choice — CONFIRM tap on a missing proposal: left the existing
  `proposal_not_found` message/path (~2012-2032) untouched. It already
  clears both `pending_action_id: None` and `collected_data["stage"]:
  None` on `InvalidConfirmationError`, i.e. it already recovers into a
  clean state today — T2's "prefer recovering into a clean state" is
  already satisfied there, so keeping the explicit message is strictly
  better (tells the patient what happened) with no correctness gap to fix.
  Design choice — "cancelar" during CREATE's own confirmation: a bare
  operation_mention of `"cancel"` is deliberately suppressed (treated as
  no mention) at this exact stage only, never treated as a request to
  switch to the cancel-appointment operation — Confirmar/Cancelar are
  this stage's own buttons, and `_is_free_text_decline` doesn't cover
  bare "cancelar" (only "cancelalo"/"cancela eso"/etc.), so this exact
  input keeps its pre-T2 behavior (ambiguous -> reminder) rather than
  silently abandoning a live proposal. Covered by
  `test_confirmation_stage_bare_cancelar_stays_a_reminder_not_a_cancel_operation`.
  RED: `test_confirmation_stage_with_a_dangling_pending_action_routes_a_fresh_create_request`
  (replays the screenshot: `STAGE_AWAITING_CONFIRMATION` + dangling
  `pending_action_id` + "Quería agendar un turno") — failed with
  `KeyError: 'collected_data'` (still returning the confirmation reminder)
  before the fix. Also RED: `..._with_no_pending_action_id_routes_a_fresh_request`,
  `test_confirmation_stage_dangling_action_no_operation_falls_back_to_menu`,
  `test_confirmation_stage_lets_a_clearly_different_operation_win_over_a_live_proposal`
  (all in `tests/unit/agent/nodes/test_appointment_node.py`). Also fixed a
  latent gap in the pre-existing `test_confirmation_stage_reminds_instead_of_advancing_on_free_text`:
  its own `pending_action_id="pa-1"` was never actually saved to the
  repository, so it was accidentally exercising the dangling-id path
  while asserting the OLD (now-changed) behavior; it now saves a real
  `pending` row so it correctly asserts the reminder still fires when
  there IS something live to confirm.
  Verification: `uv run pytest -q` → 1572 passed, 82 skipped, 5 failed
  (the 5 pre-declared known environmental failures only). `uv run ruff
  check .` → all checks passed. `uv run ruff format --check` on both
  touched files → already formatted (this also cleaned pre-existing
  formatting drift within `appointment.py`, same as T1's touched files).
  `uv run mypy app` → no issues (320 files).
  Commits: d0ece5a (code+tests), 9a5e7cd (docs).

- T2b done (`app/agent/nodes/appointment.py`, `STAGE_AWAITING_CONFIRMATION`
  free-text branch, ~1885-2030, ~1978-1996, ~2388-2394). All 4 review
  follow-ups addressed:
  1. R3-button-tap-without-pending-id-reminds: a normalization step right
     after the existing free-text-decline normalization (~1898-1910) now
     resets `button_payload` to `None` whenever it's CONFIRM/REJECT with
     `pending_action_id is None`, so the turn takes the SAME recovery path
     free text with nothing to confirm already used (the `pending_action_
     usable = False` branch two ifs below) instead of falling through the
     CONFIRM/REJECT `elif`s' own `pending_action_id is not None` guards
     into the final catch-all `else`, which used to give the identical
     reminder back forever. Design choice: since a real button tap carries
     no free-text `operation_mention`, this recovery lands on the same
     operation menu (`STAGE_AWAITING_OPERATION_SELECTION`,
     `_MAIN_MENU_RESET_MESSAGE`) a main-menu reset / the existing
     dangling-action-no-operation case already uses — not the
     `proposal_not_found` message, since that path already requires
     something to reject in the first place and a bare tap alone gives no
     new information to explain back. Updated the final `else`'s stale
     comment (~2388-2394) to match.
  2. R3-expired-row-branch-untested: pure test addition, no code change —
     the existing `existing_pending_action.status == "pending"` check
     already treated a non-pending row as unusable; added
     `test_confirmation_stage_expired_pending_action_row_routes_a_fresh_request`
     (a REAL saved row with `status="expired"`, unlike the pre-existing
     dangling-id tests which never save a row at all) to prove it.
  3. R3-new-db-lookup-unguarded: wrapped the `pending_actions.get_by_id`
     lookup (~1920-1959) in `try/except Exception` (matching this file's
     own `_staffed_specialty_ids_safe` convention: `# noqa: BLE001 --
     broad catch is intentional` + `logger.warning(..., exc_info=exc)`).
     Fail-safe direction: on error, return the SAME confirmation reminder
     this gate always gave before T2 added the lookup — never guess the
     proposal is gone and silently drop possibly-live stage/pending_action_id
     state just because the DB couldn't be asked.
  4. R3-switch-leaves-live-proposal-pending: when `operation_switch` fires
     AND `pending_action_usable` is True (~1979-1996) — i.e. there IS a
     genuinely live `pending` row being abandoned — it's now rejected via
     `RejectPendingActionUseCase` + `_cancel_follow_up`, the exact same
     use case and follow-up-cancellation call a Cancelar tap already uses,
     so there is still only one path that ever transitions a pending
     action out of `pending`. Updated
     `test_confirmation_stage_lets_a_clearly_different_operation_win_over_a_live_proposal`'s
     assertion from `status == "pending"` (the old, now-wrong expectation)
     to `status == "cancelled"`.
  RED (observed via `git stash` on `appointment.py` only, tests kept):
  `test_confirmation_stage_confirm_tap_with_no_pending_action_id_routes_a_fresh_request`
  and `..._cancelar_tap_..._routes_a_fresh_request` both failed with
  `KeyError: 'collected_data'` (still the reminder, no `collected_data` key
  in the response); `test_confirmation_stage_falls_back_to_reminder_when_pending_action_lookup_fails`
  failed with `RuntimeError: db unavailable` (unguarded, propagated);
  `test_confirmation_stage_lets_a_clearly_different_operation_win_over_a_live_proposal`
  failed on `assert 'pending' == 'cancelled'`. (Two tests in the same batch —
  the free-text-decline-without-id and the expired-row cases — already
  passed pre-fix, confirming those two sub-cases were already correct
  before T2b and needed only explicit regression coverage.)
  Verification: `uv run pytest -q` → 1577 passed, 82 skipped, 5 failed (the
  5 pre-declared known environmental failures only). `uv run ruff check .`
  → all checks passed. `uv run ruff format --check` on both touched files
  → already formatted. `uv run mypy app` → no issues (320 files).
  Commit: bb5df7d (code+tests), f04145c (docs).

- T3 done. Mapped first (via `codegraph_explore` + targeted reads, not
  broad Read/Glob): `resolve_interaction.py`'s `_GLOBAL_BUTTON_INTENTS`
  (~88-99) already mapped `MENU_LOCATION_PAYLOAD -> "location"`, "location"
  was already in `_INFORMATION_INTENTS`/`_ROUTABLE_INTENTS`, and `graph.py`
  already routed intent="location" to `LOCATION_NODE` — the deterministic
  `asks_for_location` pre-check (~203-206) and the button both already
  worked. The ONLY real gap was the LLM side: "location" was missing from
  `_UNDERSTANDING_LABELS`/`DEFAULT_UNDERSTAND_PROMPT`
  (`openai_compatible_llm_provider.py`), and the `question` bullet's own
  examples ("dirección", "cómo llegar") actively told the model to
  classify those as prose instead. Likewise, `navigation_target="main"`
  already worked mid-flow (`appointment.py` ~1795, gated by
  `_NAVIGABLE_STAGES`) — the only gap was IDLE (no stage), which the
  top-of-node navigation check never covered at all.
  Changes:
  1. `app/infrastructure/llm/openai_compatible_llm_provider.py`: added
     `"location"` to `_UNDERSTANDING_LABELS` (`_INTENT_LABELS` — used by
     the separate, narrower `classify_intent`/eval-suite path — left
     untouched, matching the task's own scope). Added a `location` bullet
     to `DEFAULT_UNDERSTAND_PROMPT` (address/where located/how to get
     there/directions/map) and removed the overlapping "dirección"/"cómo
     llegar" examples from the `question` bullet, since the prompt itself
     was steering the model to the wrong label for those phrasings.
  2. `app/agent/nodes/appointment.py`: factored the `MENU_MAIN_PAYLOAD`
     response (WELCOME_TEXT/WELCOME_LIST/`pending_action_id: None`/
     `collected_data: {}`) into one shared `_welcome_reset_response`
     helper (next to `_cancel_follow_up`), now called from all 3 sites —
     the button check (~1881), the existing mid-stage `navigation_target
     == "main"` branch (~1816), and a new `elif stage is None and
     navigation_target == "main":` branch (~1870) for idle. Design choice:
     did NOT extend this to STAGE_AWAITING_CONFIRMATION (unlike the real
     button, which fires unconditionally before any stage check) —
     `_NAVIGABLE_STAGES`'s own documented rationale is that free text must
     never bypass an explicit Confirmar/Cancelar on a live proposal (T2b's
     same principle); only a deterministic button tap gets that override
     power. Did NOT broaden idle handling to other `navigation_target`
     values (specialty/professional/slot) — out of this task's literal
     scope ("navigation_target='main' ... also idle") and untested territory.
  3. `app/infrastructure/llm/fake_llm_provider.py`: extended
     `classify_intent`/`understand()` with `_LOCATION_UNDERSTANDING_KEYWORDS`
     (phrasings the deterministic pre-check does NOT already catch, e.g.
     "cómo hago para llegar" — chosen specifically so parity tests exercise
     the NEW LLM label, not the old substring fast path) and
     `_NAVIGATION_MAIN_KEYWORDS` ("volver al menú principal" etc.), forcing
     `intent="appointment"`+`confidence=0.9` when a navigation keyword hits
     and confidence would otherwise be too low — mirrors how `resolve_
     interaction.py` already treats mid-flow navigation unconditionally
     but idle only past the confidence gate.
  4. Resolve_interaction itself needed NO routing changes — "location" and
     `navigation_target` were already the single normalization point
     (`_GLOBAL_BUTTON_INTENTS`/`_carried_understanding`); this task only
     had to teach the LLM the label and extend appointment.py's own idle
     coverage. `button_payload` was deliberately NOT set from
     `resolve_interaction`'s return to fake a "same branch" — that field's
     own documented contract is "never mutated by a node"
     (`app/agent/state.py:20-23`); `_welcome_reset_response` is the actual
     single-point-of-truth instead, one level down.
  Parity tests added (button vs free-text equivalent, per option):
  location (`test_location_free_text_llm_label_reaches_the_same_intent_as_the_button`),
  main menu idle+mid-stage (`test_menu_main_free_text_reaches_the_same_intent_as_the_button`
  in `test_resolve_interaction.py`; full-response-equality parity in
  `test_navigation_target_main_from_idle_matches_the_menu_main_button` /
  `..._mid_stage_...` in `test_appointment_node.py`), handoff
  (`test_handoff_free_text_reaches_the_same_intent_as_the_admin_button`),
  operations create/cancel/reschedule/view
  (`test_operation_free_text_reaches_the_same_intent_as_its_button`,
  parametrized), plus `test_understand_accepts_the_location_intent_label`
  in `test_openai_compatible_llm_provider.py` proving the real provider's
  parse/validation path (`_parse_understanding_result`'s `_UNDERSTANDING_
  LABELS` allowlist) now accepts "location" instead of raising
  `LLMInvalidResponseError`.
  RED (observed via `git stash` per file, tests kept): with `appointment.py`
  stashed, `test_navigation_target_main_from_idle_matches_the_menu_main_button`
  failed (`response_text` was the operation-menu fallback text, not
  `WELCOME_TEXT`) — its mid-stage sibling already passed pre-fix (that path
  pre-dates T3, confirming it was truly idle-only gap). With `fake_llm_
  provider.py` stashed, `test_menu_main_free_text_reaches_the_same_intent_as_the_button`
  and `test_location_free_text_llm_label_reaches_the_same_intent_as_the_button`
  both failed on `intent == 'unknown'`. With `openai_compatible_llm_
  provider.py` stashed, `test_understand_accepts_the_location_intent_label`
  failed with `LLMInvalidResponseError: Model returned an unrecognized
  intent label: 'location'`.
  Verification: `uv run pytest -q` → 1587 passed, 82 skipped, 5 failed (the
  5 pre-declared known environmental failures only). `uv run ruff check .`
  → all checks passed. `uv run ruff format --check` on all 6 touched files
  → 5 already formatted; `openai_compatible_llm_provider.py` reports one
  pre-existing drift spot (`DEFAULT_GENERATE_RESPONSE_PROMPT`, lines this
  task never touched) confirmed present on the pre-T3 tree too via `git
  stash` — not introduced here, left as-is (same "already formatted for
  what this task touched" pattern T1/T2 recorded). `uv run mypy app` → no
  issues (320 files).
  Commit: 4112a63 (code+tests), 5f6e94c (docs).

- T4 done. All 3 review follow-ups from review-fc1d81209235acfb addressed:
  1. R3-new-conversation-rotation-can-collide-with-prior-incarnation-
     generation (`app/application/messages/ingest_message.py:634-676`
     `_resolve_or_create_conversation`, new helper
     `_new_conversation_workflow_generation_seed` ~lines 67-100; call site
     ~lines 221-236). Root cause confirmed: a brand-new `Conversation` row
     always started at the SAME fixed dataclass default
     (`workflow_session_generation == 1`,
     `app/domain/entities/conversation.py:34`); T1's own fix rotates it
     exactly ONCE, unconditionally landing every recreated conversation on
     generation `2` — so a prior incarnation of the SAME conversation id
     that had ALSO reached generation 2 (trivial: every OTHER conversation's
     T1 rotation lands there too) would have its checkpoint thread
     (`{conversation_id}:session:2`) and any pending action still recorded
     at that generation revived by the very next real turn — the identical
     collision T1 fixed for generation 1, one generation later.
     Design choice (option (a) from this task's own brief): seed the new
     row's `workflow_session_generation` from the current epoch second
     (`int(created_at.timestamp())`) instead of the fixed default, rather
     than querying the max generation among existing pending actions for
     that conversation id (option (b)) — because `pending_actions.
     conversation_id` is a hard FK to `conversations.id`
     (`app/infrastructure/database/models/pending_action.py:17-19`), so
     whatever deleted the prior incarnation's row must already have cleared
     its pending actions first; there is nothing left in that table to query
     from in the collision scenario this fix targets. The real un-queryable
     residual risk is the LangGraph checkpoint thread, which has no FK or
     query relationship to this application's own tables at all — an
     epoch-second seed instead makes an accidental collision require the
     prior incarnation to have rotated into the hundreds of millions of
     generations, unreachable through this codebase's own rotation triggers
     (at most a handful of times a day per conversation). Checked: no schema
     migration needed — `workflow_session_generation` is already a
     `BigInteger` column (`ConversationModel`), Alembic is present
     (`migrations/versions/`) but unused here since the seed is an
     application-level default, not a DB-level one.
     `RotateWorkflowSessionUseCase.execute`
     (`app/application/conversations/rotate_workflow_session.py`) gained an
     `expire_all_pending_generations: bool = False` parameter — when `True`
     (only ever passed from `ingest_message.py`'s `is_new_conversation`
     branch), it expires EVERY still-pending action for the conversation id
     via `get_pending_for_conversation` instead of only the one exact
     `expected_generation` `get_pending_for_conversation_generation`
     filters on — defensive belt-and-suspenders for the FK argument above,
     in case a particular deployment's delete path doesn't hold it. The
     inactivity-rotation call site (still-existing row, genuinely one
     generation retiring at a time) keeps the narrower default unchanged.
     RED: `test_new_conversation_never_collides_with_a_higher_prior_
     incarnation_generation` (`tests/unit/application/messages/
     test_ingest_message.py`) — stale pending actions seeded at
     generations 1, 2, AND 5 for a conversation id about to be created
     fresh; failed with `assert 3 > 1000000` (old fixed-default behavior:
     1 -> rotated to 2, only expiring generation-1, colliding with the
     generation-2 stale row) before the fix. Also RED:
     `test_expire_all_pending_generations_clears_every_older_generation`
     (`tests/unit/application/conversations/
     test_rotate_workflow_session.py`) — failed with `TypeError:
     ...unexpected keyword argument 'expire_all_pending_generations'`
     before the fix.
  2. R3-operation-switch-reject-unguarded (`app/agent/nodes/appointment.py`
     ~1999-2023): the T2b-added reject of a live proposal on operation
     switch only ever caught `InvalidConfirmationError`/
     `PendingActionExpiredError` — a repository/provider failure (on the
     `proposal_repositories_provider()` context entry, the
     `RejectPendingActionUseCase.execute` call, or `_cancel_follow_up`) was
     completely unguarded and would blow up the whole turn. Wrapped the
     whole block in `try/except Exception` (same
     `# noqa: BLE001 -- broad catch is intentional` + `logger.warning(...,
     exc_info=exc)` convention as the T2b lookup guard right above it), but
     the OPPOSITE fail-safe direction: the lookup guard falls back to the
     reminder (preserve state on doubt, since there's no explicit new
     request yet to serve); this one still lets the switch through, since
     the patient's new request is already explicit and a cleanup failure on
     the OLD proposal must never trap them back in the old flow.
     RED: `test_confirmation_stage_switch_continues_even_when_rejecting_
     the_live_proposal_fails` (`tests/unit/agent/nodes/
     test_appointment_node.py`) — a `FakePendingActionRepository` subclass
     raising on `.save()` only when the incoming status is `"cancelled"`
     (letting the initial `"pending"` save through), so only the REJECT's
     own write fails, not the earlier usability lookup; failed with an
     unguarded `RuntimeError: db unavailable` propagating out of `node()`
     before the fix.
  3. R3-fake-classify-intent-diverges-from-real-labels
     (`app/infrastructure/llm/fake_llm_provider.py:194-238`): the fake's
     `classify_intent` could return `"location"`, but the real provider's
     `_INTENT_LABELS` (`openai_compatible_llm_provider.py:40-46` — the
     narrow allowlist `classify_intent` validates against, confirmed via
     `_parse_intent_result`'s `if intent not in _INTENT_LABELS` check at
     line 447) never includes it; only the separate, richer
     `_UNDERSTANDING_LABELS = (*_INTENT_LABELS, "question", "location")`
     (line 79, T3's own addition) does. Moved the `_LOCATION_UNDERSTANDING_
     KEYWORDS` check out of `classify_intent` entirely and into
     `understand()` only (checked BEFORE delegating to `classify_intent`
     for every other label), so `classify_intent` can never diverge from
     what the real provider's own narrow classifier could return. Checked
     both call sites: `classify_intent`'s own tests
     (`tests/unit/infrastructure/llm/test_fake_llm_provider.py`) never
     asserted a `"location"` result, and `resolve_interaction.py`'s
     location parity test (`test_resolve_interaction.py`) already went
     through `understand()`, not `classify_intent` — no other test needed
     adjusting.
     RED: `test_classify_intent_never_returns_location`
     (`tests/unit/infrastructure/llm/test_fake_llm_provider.py`) — failed
     with `AssertionError: assert 'location' != 'location'` before the fix.
     Companion `test_understand_still_recognizes_location_after_classify_
     intent_narrowing` already passed pre-fix (confirming `understand()`'s
     own coverage was untouched by the narrowing) and pins the behavior
     going forward.
  Verification: `uv run pytest -q` → 1592 passed, 82 skipped, 5 failed (the
  5 pre-declared known environmental failures only — confirmed by name:
  4 in `test_gateway_dependency.py`, 1 in `test_internal_eval_wiring.py`).
  `uv run ruff check .` → all checks passed. `uv run ruff format --check`
  on all 8 touched files → 7 already formatted; `test_fake_llm_provider.py`
  reports 2 pre-existing drift spots (lines untouched by this task,
  confirmed present on the pre-T4 tree via `git stash` — same "already
  formatted for what this task touched" pattern T1/T3 recorded, left
  as-is). `uv run mypy app` → no issues (320 files).
  Commit: 6c2ce48 (code+tests).

## Next step

Feature complete (T1, T2, T2b, T3, T4 all done). Optional follow-ups,
neither blocking, both pre-existing and unrelated to this feature's own
diff: the `ruff format` drift in `openai_compatible_llm_provider.py`'s
`DEFAULT_GENERATE_RESPONSE_PROMPT` (T3's note) and in
`test_fake_llm_provider.py`'s two untouched call sites (T4's note above).
