# CTWA ad attribution (step 1: capture + echo safety)

## Objective
Capture the Click-to-WhatsApp (CTWA) `referral` object Meta attaches to the first inbound
message of a lead who clicked a Facebook/Instagram ad, persist it per conversation, and make
sure Meta's own ad welcome message (business-sent, NOT sent by our bot) can never silence the
bot for ad leads. The KPI endpoint/UI is out of scope for this unit of work.

## Constraints
- YCloud's exact JSON nesting for the referral is unknown (assumed to mirror Meta, under
  `whatsappInboundMessage.referral`). Capture must be tolerant and keep the raw object.
- No network calls, no push/PR. Conventional commits, English only.
- ~400 changed lines per task is only an advisory heuristic.

## Authorized scope
app/infrastructure/ycloud, app/application/messages, app/application/conversations,
app/domain/entities, app/domain/repositories, app/infrastructure/database,
migrations/versions/0024_ctwa_ad_referrals.py, app/api/dependencies, tests, README.md.
(Also touched, necessarily: `app/api/routes/webhook.py` to wire the echo guard.)

## Tasks
- [x] T1a Tolerant capture: `referral`/`context` on `YCloudInboundMessage` (non-dict values become
  `None`), pure normalizer `app/infrastructure/ycloud/referral.py`, `AdReferralDTO` on
  `InboundMessageDTO`, parser reads `referral` then `context.referral`.
- [x] T1b Persistence: `conversation_ad_referrals` (model, entity, port, SQL + fake repository,
  migration `0024_ctwa_ad_referrals`), saved from `IngestMessageUseCase` right after the
  contact/conversation exist, idempotent per (conversation, source_id), failure only logged.
- [x] T2 Echo safety: guard in `HandleSmbMessageEchoUseCase` (see below).

## Route declaration
Single writer, inline (delegated by the parent as the sole writer). No explorer needed: the
mapped surface was read directly.

## Design notes
- Idempotency: unique index on `(conversation_id, coalesce(source_id, ''))`; the SQL repository
  checks first, then inserts inside a savepoint (`begin_nested`) so a rejected row never poisons
  the ingest transaction. A missing ad id counts as one shared value per conversation.
- Raw object: strings over 2 KB dropped, depth capped at 4, lists capped at 50 items; if the JSON
  still exceeds 8 KB it is replaced by `{"_truncated": true, "keys": [...]}`.
- Referral is stored before the welcome/agent steps, so it exists when any later echo arrives.

## T2 investigation: echo safety
- Risk is real. `app/api/routes/webhook.py` sends every `whatsapp.smb.message.echoes` event to
  `HandleSmbMessageEchoUseCase.execute`, whose `mode == "agent"` branch flips the conversation to
  `human`, sets `input_state=HUMAN` and stamps `last_human_reply_at` for ANY echoed text that is
  not `/bot` (`handle_smb_message_echo.py`, branch `conversation.mode == "agent" and not
  is_reactivation_command`). The route then also applies the Chatwoot `administracion` label.
  Meta's CTWA welcome is sent from the business number right after the lead's first message,
  i.e. after our ingest created the conversation. If YCloud echoes it, every ad lead would be
  paused. Nothing in the payload lets us tell it apart from staff text (it is unverified).
- `whatsapp.message.updated` is unaffected: it only handles `status="failed"` for ids we
  recorded in `sent_messages` and never changes the mode.
- Guard (narrowest justifiable): `AD_WELCOME_ECHO_WINDOW = 60 s`. An echo is ignored (no mode
  flip, no `last_human_reply_at`, no `administracion` label; the text is still mirrored to
  Chatwoot) only when ALL hold: the conversation is in agent mode, the conversation has an ad
  referral whose latest `first_seen_at` is within 60 s, and the echo is not `/bot` or `/adm`.
  A referral lookup failure falls back to the old behavior. Trade-off: a real staff reply typed
  within a minute of an ad lead's first message does not pause the bot.
- Assumption to confirm with the first real ad lead: whether the welcome arrives as an echo at
  all. If it does not, the guard is inert.

## Evidence / commits
- T1a `ecec40a` feat(ycloud): capture the CTWA ad referral from inbound messages
- T1b `32975ca` feat(attribution): persist the CTWA ad referral per conversation
- T2 + docs: see the `fix(echo)` commit that follows in `git log` (recorded below once made).

## Verification
- `uv run pytest tests/unit -q` (replay file deselected): 4026 passed, 3 failed (the known
  pre-existing `test_gateway_dependency.py` failures).
- `uv run ruff check app tests`, `uv run ruff format --check app tests`, `uv run mypy app`: clean.
- Real Postgres 16 (throwaway container on 127.0.0.1:55432, removed afterwards): `alembic upgrade
  head`, `downgrade 0023_agent_pause_filter`, `upgrade head` all OK; new integration tests
  (7) and `tests/integration/test_migrations.py` pass. `alembic check` reports four pre-existing
  index drifts unrelated to this table.
- Not verified: the real YCloud referral shape and whether Meta's welcome arrives as an echo.

## Next (not in this unit of work): KPI section
- Ad leads = distinct conversations with a referral in the period, by `source_id` and by day.
- Booked = those conversations with a confirmed `create_appointment` action and tool evidence.
- Conversion rate = booked / ad leads; list ads without bookings.
- Same "via bot only" caveat as the existing KPIs (bookings made outside the bot are invisible).
