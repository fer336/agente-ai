# Chatwoot label control and full mirror

## Objective

Clinic staff can pause and resume the agent from Chatwoot with the `administracion`
label, and the Chatwoot inbox shows the whole WhatsApp conversation.

## Problem

- Chatwoot labels are write-only: the bot pushes `agente`/`administracion` on mode
  changes, but a label staff add or remove by hand changes nothing.
- A staff reply sent from Chatwoot reaches WhatsApp but does not pause the bot, so the
  bot and the human can both answer the patient.
- `assign_administracion`/`assign_bot` replace the whole label set, wiping any other
  label staff applied.
- Not mirrored: inbound audio transcripts, outbound location cards, Flow submission
  field values.

## Why

Staff operate from Chatwoot (YCloud tags are unreliable for Coexistence contacts), so
Chatwoot has to be both the control surface and the complete record.

## Product decision (user, 2026-09-25)

- Adding `administracion` in Chatwoot pauses the bot (`conversation.mode = "human"`).
- Removing `administracion`, or resolving the conversation, resumes the bot.

## Scope

- Chatwoot webhook: handle `conversation_updated` label changes (add → pause,
  remove → resume); react only to an actual `administracion` transition.
- Staff reply via Chatwoot pauses the bot and labels `administracion`.
- Label writes become additive/subtractive (read-modify-write), never a full replace.
- Mirror inbound audio transcripts, outbound locations, Flow submission values.

Out of scope: image/attachment mirroring, `X-Chatwoot-Signature` HMAC verification,
provisioning the live Chatwoot webhook subscription (remote, needs explicit
authorization).

## Constraints

- Mirror stays best-effort: never raises, never delays the patient-facing turn.
- Own label writes must not loop back into mode flips (idempotent handling).
- Hexagonal layering; strict TDD (RED → GREEN → REFACTOR).
- Webhook payload shape must be verified against Chatwoot source, not assumed.

## Tasks

- [ ] T1 — Additive label writes: `ChatwootClient` reads labels
  (`GET /conversations/{id}/labels`); gateway gains add/remove label semantics;
  `assign_administracion`/`assign_bot` keep unrelated staff labels.
- [ ] T2 — Label-driven mode: webhook handles `conversation_updated`; adding
  `administracion` → mode human; removing it → mode agent (same effect as resolved);
  no-op when mode already matches; ignore updates without a label transition.
- [ ] T3 — Staff reply pauses the bot: `message_created` from a human agent sets
  mode human (+ `last_human_reply_at`) and labels `administracion`.
- [ ] T4 — Full mirror: inbound audio transcript, outbound location, Flow submission
  values.

## Acceptance criteria

- Adding/removing `administracion` in Chatwoot pauses/resumes the bot on the next
  patient message.
- A staff reply from Chatwoot never leaves the bot answering in parallel.
- Unrelated staff labels survive handoff and reactivation.
- Audio transcripts, locations and Flow answers appear in the Chatwoot conversation.

## Checks

- TDD: strict, source = session config ("Strict TDD Mode: enabled"), runner `uv run pytest`.
- Per task: `uv run pytest` (full, incl. integration), `uv run ruff check .`,
  `uv run mypy app/`.
- Known failures on main: 4 in `tests/unit/api/dependencies/test_gateway_dependency.py`,
  1 in `test_internal_eval_wiring.py`.

## Delivery

- Branch `feat/chatwoot-label-control` off main `a02eccd`.
- Forecast ~700 authored changed lines (above the ~400 budget); strategy `ask-on-risk`,
  chain strategy `stacked-to-main` (user, 2026-09-25).
- Slice 1 (PR A): T1–T3 on `feat/chatwoot-label-control` → main.
- Slice 2 (PR B): T4 on `feat/chatwoot-full-mirror`, branched off main (independent of
  slice 1) → main.

## Routes

- T1–T3: delegated direct (writer), 2+ non-trivial files per task.
- T4: delegated direct (writer), 2+ non-trivial files.

## Progress

- Exploration done (mapping report, 2026-09-25). No tasks started.

## Next step

T1.
