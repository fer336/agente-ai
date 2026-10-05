# Appointment-reminder staged rollout runbook

## Safe state first

**Reminders are off by default.** `APPOINTMENT_REMINDERS_ENABLED=false` and an empty `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST` blocks every send. Both controls must be changed deliberately before the worker schedules or delivers anything.

This runbook is for an operator conducting a deliberately narrow rollout. **No live send was performed while creating this documentation.** Production deployment and production enablement remain manual operator actions.

## Preflight

1. Confirm the service is using the intended dotenv/secret source; do not place credentials in this document or in version control.
2. Run the required migration before starting or restarting the application:

   ```bash
   uv run alembic upgrade head
   uv run alembic current
   ```

   The database must be upgraded through the single current head
   `0020_review_opt_out`; the linear chain applies both
   `0019_appointment_reminder` (durable `appointment_reminders` rows) and
   `0020_review_opt_out` (the `contacts.review_opted_out_at` preference).
3. Verify the three approved template names are available in the configured WhatsApp provider account before enabling any send:
   - `recordatorio_turno_confirmar`
   - `recordatorio_turno_ubicacion`
   - `solicitud_resena_google`

## Staged test: one authorized number only

Do not invent or substitute a recipient. Obtain explicit authorization for **one** E.164 test number, then make that one number the complete allowlist.

1. Keep `APPOINTMENT_REMINDERS_ENABLED=false` while adding only the authorized number to `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST`; use E.164 format (for example, the authorized number itself, not a placeholder or a patient number copied into a ticket).
2. Restart/reload the application using the normal environment-management procedure and confirm the loaded allowlist contains only that number. Do not enable a broader list.
3. Set `APPOINTMENT_REMINDERS_ENABLED=true`, restart/reload through the normal procedure, and watch logs and aggregate database state. The worker must schedule/deliver only for the authorized number; do not print phone numbers, names, message text, or other patient data in shared evidence.
4. Exercise and record each path below against planned test appointments whose clinic-local time makes the path due. Check the actual template and timing, not only that a row exists:

   | Path | Eligibility and timing | Expected template/callback |
   | --- | --- | --- |
   | Day-before confirmation | `active` or `confirmed` appointment; previous clinic day at `APPOINTMENT_REMINDERS_DAY_BEFORE_TIME` | `recordatorio_turno_confirmar`; confirm and cancel quick replies |
   | Same-day reminder/location | `active` or `confirmed` appointment; `APPOINTMENT_REMINDERS_SAME_DAY_OFFSET_HOURS` before start, only inside the configured send window | Active: confirmation template with confirm/cancel. Confirmed: `recordatorio_turno_ubicacion` with location quick reply. |
   | Review request | `attended` appointment; next clinic day at `APPOINTMENT_REMINDERS_REVIEW_TIME` | `solicitud_resena_google`; its static URL and review opt-out quick reply |

5. Test callbacks from the same authorized number: confirmation updates the appointment; cancellation requires the follow-up confirmation; location responds only for the matching sent reminder; review opt-out records the preference and suppresses later review requests. Treat a stale/mismatched callback as safely unavailable, not as permission to retry against another recipient.
6. Keep the allowlist at one number while reviewing evidence. Decide on expansion in a separate, explicit approval; expansion is not part of this test.

## Reminder environment settings

These settings and defaults are already documented in [`dotenv_example_template.txt`](../dotenv_example_template.txt). Preserve the safe defaults until the staged test is approved.

| Variable | Default | Operator meaning |
| --- | --- | --- |
| `APPOINTMENT_REMINDERS_ENABLED` | `false` | Master opt-in; it does not bypass the allowlist. |
| `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST` | empty | Comma-separated E.164 recipients; empty blocks all sends. |
| `APPOINTMENT_REMINDERS_CONFIRMATION_TEMPLATE_NAME` | `recordatorio_turno_confirmar` | Day-before and active same-day template. |
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

## Observe and verify

Run the focused checks before rollout; they do not perform a live provider send:

```bash
uv run alembic upgrade head
uv run alembic current
uv run --extra dev pytest tests/unit/application/reminders tests/unit/workers/test_appointment_reminder_worker.py tests/unit/infrastructure/database/repositories/test_appointment_reminder_repository.py tests/unit/agent/nodes/test_reminder_action_node.py tests/unit/api/routes/test_webhook.py
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

1. Set `APPOINTMENT_REMINDERS_ENABLED=false`.
2. Remove the number(s) from `APPOINTMENT_REMINDERS_PHONE_ALLOWLIST` (leave it empty to block all sends).
3. Restart/reload the application via the normal operational procedure.
4. Preserve reminder and opt-out rows, collect only privacy-safe aggregate/log evidence, and investigate before any re-enable. Operational rollback does not downgrade the database migrations; the additive tables/column remain in place while sends are disabled.

## Review-policy guardrails

Review requests apply to **all attended eligible patients** in scope, subject to the configured cooldown and a recorded opt-out. Do not sentiment-gate recipients, offer incentives, or suppress negative experiences. Honor review opt-out requests: they suppress review requests while appointment reminders remain independently eligible.

## Rollout exit checklist

- [ ] Migrations report `0020_review_opt_out` as the single current head, with `0019_appointment_reminder` applied earlier in the chain.
- [ ] The allowlist contained exactly one explicitly authorized E.164 test number during the trial.
- [ ] All three template/timing paths and their callbacks were observed for that number.
- [ ] Logs and aggregate DB checks showed no out-of-scope recipient activity.
- [ ] Review-policy constraints and opt-out behavior were verified.
- [ ] Expansion, if any, has a separate recorded approval.
