# Appointment-reminder staged rollout runbook

## Safe state first

**Reminders are off by default.** `APPOINTMENT_REMINDERS_ENABLED=false` and the safe default `APPOINTMENT_REMINDERS_ROLLOUT_MODE=allowlist` fail closed. In `allowlist` mode, an empty `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST` blocks every send; an empty allowlist never implies `all`. Both controls must be changed deliberately before the worker schedules or delivers anything.

This runbook is for an operator conducting a deliberately narrow rollout. **No live send was performed while creating this documentation.** Production deployment and production enablement remain manual operator actions. Mode changes require the normal application restart/reload.

## Preflight

1. Confirm the service is using the intended dotenv/secret source; do not place credentials in this document or in version control.
2. Run the required migration before starting or restarting the application:

   ```bash
   uv run alembic upgrade head
   uv run alembic current
   ```

   The database must be upgraded through the single current head
   `0021_reminder_appointment_start`; the linear chain applies
   `0019_appointment_reminder` (durable `appointment_reminders` rows),
   `0020_review_opt_out` (the `contacts.review_opted_out_at` preference) and
   `0021_reminder_appointment_start` (the nullable `appointment_reminders.appointment_starts_at` column).
3. Verify the four approved template names are available in the configured WhatsApp provider account before enabling any send, with the definitions in [Template definitions](#template-definitions-metaycloud):
   - `recordatorio_turno_confirmar`
   - `recordatorio_turno_sin_confirmar`
   - `recordatorio_turno_ubicacion`
   - `solicitud_resena_google`

## Staged test: one authorized number only

Do not invent or substitute a recipient. Obtain explicit authorization for **one** E.164 test number, then make that one number the complete allowlist.

1. Keep `APPOINTMENT_REMINDERS_ENABLED=false`, explicitly set `APPOINTMENT_REMINDERS_ROLLOUT_MODE=allowlist`, and add only the authorized number to `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST`; use E.164 format (the authorized number itself, not a placeholder or a patient number copied into a ticket).
2. Restart/reload the application using the normal environment-management procedure and confirm the loaded mode is `allowlist` and the loaded allowlist contains only that number. Do not enable a broader list.
3. Set `APPOINTMENT_REMINDERS_ENABLED=true`, restart/reload through the normal procedure, and watch logs and aggregate database state. The worker must schedule/deliver only for the authorized number; do not print phone numbers, names, message text, or other patient data in shared evidence.
4. Exercise and record each path below against planned test appointments whose clinic-local time makes the path due. Check the actual template and timing, not only that a row exists:

   | Path | Eligibility and timing | Expected template/callback |
   | --- | --- | --- |
   | Day-before confirmation | `active` or `confirmed` appointment; previous clinic day at `APPOINTMENT_REMINDERS_DAY_BEFORE_TIME` | `recordatorio_turno_confirmar`; one "Confirmar turno" quick reply |
   | Same-day reminder/location | `active` or `confirmed` appointment; `APPOINTMENT_REMINDERS_SAME_DAY_OFFSET_HOURS` before start, only inside the configured send window | Active (not confirmed): `recordatorio_turno_sin_confirmar` with "Confirmar turno" and "Reprogramar turno" quick replies. Confirmed: `recordatorio_turno_ubicacion` with location quick reply. |
   | Review request | `attended` appointment; next clinic day at `APPOINTMENT_REMINDERS_REVIEW_TIME` | `solicitud_resena_google`; its static URL and review opt-out quick reply |

5. Test callbacks from the same authorized number: confirmation updates the appointment; rescheduling starts the reschedule flow for that appointment; location responds only for the matching sent reminder; review opt-out records the preference and suppresses later review requests. Treat a stale/mismatched callback as safely unavailable, not as permission to retry against another recipient.
6. Keep the allowlist at one number while reviewing evidence. Decide on expansion in a separate, explicit approval; expansion is not part of this test.

## Template definitions (Meta/YCloud)

Create or edit these templates in the WhatsApp provider account **before** deploying this code. Category `UTILITY`, language `es_AR` (`APPOINTMENT_REMINDERS_TEMPLATE_LANGUAGE`). Body variables are positional: `{{1}}` patient name, `{{2}}` date such as `jueves 8 de octubre`, `{{3}}` time as `HH:MM`. Use the sample values `Sofía` / `jueves 8 de octubre` / `10:30` when submitting for review. Buttons are quick replies; the application supplies each button's payload at send time, so the buttons carry no payload in the template itself.

| Template | Action | Body variables | Quick-reply buttons (index: label) |
| --- | --- | --- | --- |
| `recordatorio_turno_confirmar` | **Edit** the existing template | `{{1}}` name, `{{2}}` date, `{{3}}` time | `0`: "Confirmar turno" (the only button; remove the former cancel button) |
| `recordatorio_turno_sin_confirmar` | **Create** (new) | `{{1}}` name, `{{2}}` date, `{{3}}` time | `0`: "Confirmar turno"; `1`: "Reprogramar turno" |
| `recordatorio_turno_ubicacion` | Unchanged | name, time | `0`: location button |
| `solicitud_resena_google` | Unchanged | name | `0`: static review URL; `1`: review opt-out quick reply |

Body of `recordatorio_turno_confirmar`:

```text
¡Hola, {{1}}! 😊 Somos de Smiling Pilar. Tenemos reservado tu turno para el *{{2}} a las {{3}}* 🦷✨
*¿Contamos con vos?* Tocá el botón de abajo para confirmar tu asistencia. ✅ ¡Te esperamos! 💙
```

Body of `recordatorio_turno_sin_confirmar` (the wording of the confirm line may still change):

```text
¡Hola, {{1}}! 😊 Vimos que todavía no confirmaste tu turno para el *{{2}} a las {{3}}*.
*¡Todavía estás a tiempo de confirmar!* ✅ *¿Preferís que lo reprogramemos?* Tocá «Reprogramar turno»
y te ayudamos a elegir otro día y horario. 💙
```

Button payloads sent by the application (for reference, not for the template): `REMINDER_CONFIRM:<appointment_id>` (index 0), `REMINDER_RESCHEDULE:<appointment_id>` (index 1 of the unconfirmed template), `REMINDER_LOCATION:<appointment_id>`, `REMINDER_REVIEW_OPTOUT`. The "Cancelar" button no longer exists in any template; a patient can still cancel by talking to the agent.

### Deploy order warning

The code and the Meta/YCloud approval must switch **together**:

- The code sends one button for the confirm template and two buttons for the unconfirmed template. A template whose approved definition does not match (for example the old two-button version of `recordatorio_turno_confirmar`) can be rejected by the provider or send a different button set than the application expects.
- An edited template goes back through Meta review, which can take **up to 24 hours**. How the previously approved version behaves while the edit is in review is not documented by the provider: do not assume it stays usable.
- Recommended order: submit both templates and wait for approval; keep `APPOINTMENT_REMINDERS_ENABLED=false` (or the single-number allowlist) until both show as approved; then deploy this release and run the staged one-number test below.
- Roll back by disabling reminders first (see incident handling); reverting the code alone does not restore the old template definition.

## What a reply does

- **Buttons are deterministic.** A tap on "Confirmar turno", "Reprogramar turno" or the location button is processed by the reminder action for that exact appointment and recipient; it does not depend on agent memory. "Reprogramar turno" starts the existing reschedule flow for that appointment.
- **First inbound.** Right after a successful send (every reminder kind) the worker creates the recipient's contact and conversation (`ycloud-{phone}`, mode `agent`) if they do not exist and stores one assistant message with a readable Spanish equivalent of the template (name, date and time only). It does not set `workflow_last_activity_at`, does not schedule the idle reset and is not mirrored to Chatwoot. Because the conversation already exists, the recipient's first free-text message (for example "hola") goes straight to the agent and does **not** receive the once-ever welcome menu. If this step failed, a first-ever reminder button tap is still processed (the welcome menu is skipped for reminder payloads); a first free-text message from such a recipient still gets the welcome menu.
- **Free text.** For up to 48 hours after a sent day-before or same-day reminder, and only while the appointment has not started, the agent receives a short note with the appointment date and time and what the reminder asked (appended to the contact memory summary that the agent already reads). A message such as "no puedo ir" therefore reaches an agent that knows which appointment it is about. There is no extra intent routing.
- **Idle cleanup deferral and rescheduling.** The idle cleanup (wipes the agent checkpoints and contact memory three hours after the last inbound message) is skipped, with outcome `skipped_pending_reminder`, while a sent day-before or same-day reminder exists for the patient's phone whose appointment start is still in the future. The skipped cleanup is rescheduled once (one scheduled idle action per conversation) for the appointment start plus the idle delay (`CONVERSATION_IDLE_RESET_DELAY_SECONDS`, default 10800), and it runs normally then. A newer inbound message replaces that schedule with the usual three-hour idle timer, which re-checks the same condition when it fires. Reminder rows created before `0021_reminder_appointment_start` have no appointment start and never defer the cleanup or add reply context. Human/Chatwoot-handled conversations are still skipped.
- **Review requests.** Unchanged: after a `review_request` is sent the worker still starts a fresh agent session (see below), after the conversation record above has been created.

## Dentalink state facts

- A "Confirmar turno" tap writes Dentalink appointment state `22` ("Confirmado por pcte. vía WhatsApp"), only after the application re-validates ownership and the current appointment state, and only if state `22` still has exactly that name and is enabled and not a cancellation state; otherwise it fails closed.
- Sending a reminder does **not** change the Dentalink appointment state; an appointment stays `active` until the patient confirms it (or the clinic changes it). The same-day job uses that state to choose the confirmed (location) or unconfirmed (confirm/reschedule) template at send time.

## Reminder environment settings

These settings and defaults are already documented in [`dotenv_example_template.txt`](../dotenv_example_template.txt). Preserve the safe defaults until the staged test is approved.

| Variable | Default | Operator meaning |
| --- | --- | --- |
| `APPOINTMENT_REMINDERS_ENABLED` | `false` | Master opt-in; it must be `true` in every sending mode. |
| `APPOINTMENT_REMINDERS_ROLLOUT_MODE` | `allowlist` | Safe staged mode. `all` is an explicit production mode; changing modes requires restart/reload. |
| `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST` | empty | Comma-separated E.164 recipients used only in `allowlist` mode; empty blocks all sends in that mode and never implies `all`. |
| `APPOINTMENT_REMINDERS_CONFIRMATION_TEMPLATE_NAME` | `recordatorio_turno_confirmar` | Day-before template (one "Confirmar turno" button). |
| `APPOINTMENT_REMINDERS_UNCONFIRMED_TEMPLATE_NAME` | `recordatorio_turno_sin_confirmar` | Same-day template for unconfirmed appointments (confirm and reschedule buttons). |
| `APPOINTMENT_REMINDERS_LOCATION_TEMPLATE_NAME` | `recordatorio_turno_ubicacion` | Confirmed same-day location template. |
| `APPOINTMENT_REMINDERS_REVIEW_TEMPLATE_NAME` | `solicitud_resena_google` | Attended-appointment review template. |
| `APPOINTMENT_REMINDERS_TEMPLATE_LANGUAGE` | `es_AR` | Provider template language. |
| `APPOINTMENT_REMINDERS_DAY_BEFORE_TIME` | `18:00` | Clinic-local day-before send time. |
| `APPOINTMENT_REMINDERS_SAME_DAY_OFFSET_HOURS` | `3` | Hours before appointment for same-day candidate. |
| `APPOINTMENT_REMINDERS_SEND_WINDOW_START` / `APPOINTMENT_REMINDERS_SEND_WINDOW_END` | `09:00` / `20:00` | Inclusive clinic-local window for same-day candidate. |
| `APPOINTMENT_REMINDERS_REVIEW_TIME` | `10:00` | Clinic-local next-day review send time. |
| `APPOINTMENT_REMINDERS_REVIEW_COOLDOWN_DAYS` | `90` | Per-patient review-request cooldown. |
| `APPOINTMENT_REMINDERS_POLL_INTERVAL_SECONDS` | `60` | Worker poll interval. |
| `APPOINTMENT_REMINDERS_BATCH_SIZE` | `50` | Maximum due rows handled per tick. |
| `APPOINTMENT_REMINDERS_MAX_ATTEMPTS` | `3` | Retry limit for delivery failures. |
| `APPOINTMENT_REMINDERS_CLAIM_TIMEOUT_SECONDS` | `300` | Delivery-claim lease; keep above the provider request bound. |
| `APPOINTMENT_REMINDERS_RETRY_BACKOFF_SECONDS` | `60` | Initial retry backoff; retries increase exponentially. |

## Production expansion: explicit `all` mode

Only after the staged trial has a separate recorded approval, set `APPOINTMENT_REMINDERS_ROLLOUT_MODE=all` and restart/reload through the normal environment-management procedure. Do **not** add every production number to the allowlist. In `all` mode, every otherwise eligible normalized Dentalink patient may receive reminders, but sends still require `APPOINTMENT_REMINDERS_ENABLED=true`.

The following safeguards remain in force in `all` mode:

- appointment state eligibility;
- configured timing and send-window checks;
- review-request cooldown;
- recorded review opt-out;
- phone normalization and validation;
- durable idempotency/claim handling; and
- delivery-time revalidation for stale or mismatched appointments.

An empty allowlist never switches the system to `all`; only the explicit mode setting does. Deployment and enablement remain manual operator actions.

## Observe and verify

Run the focused checks before rollout; they do not perform a live provider send:

```bash
uv run alembic upgrade head
uv run alembic current
uv run --extra dev pytest tests/unit/application/reminders tests/unit/application/conversations/test_cleanup_conversation_session.py tests/unit/workers/test_appointment_reminder_worker.py tests/unit/infrastructure/database/repositories/test_appointment_reminder_repository.py tests/unit/agent/nodes/test_reminder_action_node.py tests/unit/api/routes/test_webhook.py
```

Watch for these structured event names (identifiers and error types only; avoid adding PII to log searches or evidence):

- `appointment_reminder_worker.tick_completed` and `appointment_reminder_worker.tick_failed`
- `appointment_reminder.sent`
- `appointment_reminder.skipped` with `recipient_not_allowlisted`, `stale_or_mismatch`, or `ineligible_state`
- `appointment_reminder.delivery_failed`
- `appointment_reminder.schedule_invalid`
- `webhook.received` for provider callbacks; `webhook.delivery_failure_unattributed` indicates an outbound delivery-status failure that could not be matched to an existing sent-message record.

At a high level, use a read-only, aggregate-only database view during the trial:

- Group `appointment_reminders` by `kind` and `status`, and compare counts to the one-number test plan; inspect timestamps, attempt counts, and presence of provider message IDs only when needed for incident correlation.
- Confirm review opt-out state through aggregate/count-based checks of `contacts.review_opted_out_at`; do not export contact names, numbers, or message content.
- Confirm no unexpected `pending`, `processing`, `failed`, or `sent` rows are accumulating outside the approved test scope. Do not delete rows to make the check pass.

## Delivery guarantee and incident handling

The database claim and terminal `sent` state prevent normal concurrent re-sends, but the system has one known exactly-once crash window: if the provider accepts a template send and the process crashes before `mark_sent` is stored, the stale claim can later be retried and may duplicate that message. The provider does not supply an idempotency key for this operation. Preserve the durable row and investigate provider/message identifiers and timestamps; do not delete rows as a recovery action.

For any unexpected recipient, template, timing, callback, or delivery failure:

1. First set `APPOINTMENT_REMINDERS_ENABLED=false`.
2. Set `APPOINTMENT_REMINDERS_ROLLOUT_MODE=allowlist` and leave `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST` empty to block all sends.
3. Restart/reload the application via the normal operational procedure.
4. Preserve reminder and opt-out rows, collect only privacy-safe aggregate/log evidence, and investigate before any re-enable. Operational rollback does not downgrade the database migrations; the additive tables/column remain in place while sends are disabled.

## Review-policy guardrails

Review requests apply to **all attended eligible patients** in scope, subject to the configured cooldown and a recorded opt-out. Do not sentiment-gate recipients, offer incentives, or suppress negative experiences. Honor review opt-out requests: they suppress review requests while appointment reminders remain independently eligible.

## Fresh agent session after a review request

Right after a `review_request` is sent and marked `sent`, the worker starts a fresh agent session for that patient: the conversation's workflow session generation is rotated (+1) and the contact's compacted memory (database row and cache key) is cleared. This is scoped to one patient; it is not a table truncate.

- Skipped, with no error: unknown contact, missing conversation, a conversation whose contact does not match, `mode` other than `agent` (human/Chatwoot handoff keeps its context), and a lost rotation race (memory is only cleared when the rotation won).
- Only `review_request` triggers it; other reminder kinds never do.
- History is kept: messages, checkpoints, and agent runs are not deleted, and the old thread stays under the previous generation.
- Failures are isolated: the reminder stays `sent`, the tick continues, and the log shows `appointment_reminder.on_sent_failed` (error type only, no phone numbers). Outcomes appear as `appointment_reminder_worker.fresh_session ... outcome=<value>`.

## Rollout exit checklist

- [ ] Migrations report `0021_reminder_appointment_start` as the single current head, with `0019_appointment_reminder` and `0020_review_opt_out` applied earlier in the chain.
- [ ] The edited and the new template are approved at the provider before reminders are enabled.
- [ ] The allowlist contained exactly one explicitly authorized E.164 test number during the trial.
- [ ] All template/timing paths (day-before, same-day unconfirmed, same-day confirmed, review) and their callbacks were observed for that number.
- [ ] Logs and aggregate DB checks showed no out-of-scope recipient activity.
- [ ] Review-policy constraints and opt-out behavior were verified.
- [ ] Expansion, if any, has a separate recorded approval.
