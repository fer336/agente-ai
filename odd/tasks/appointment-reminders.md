# Appointment reminders and review requests

## Objective

Send approved YCloud WhatsApp templates for appointment confirmation, same-day
location help, and post-visit Google review requests without contacting real patients
until the feature is explicitly enabled and a recipient is allowlisted.

## Product decision (user, 2026-10-04)

Use a safe staged rollout in an isolated worktree:

- Day-before confirmation reminder at 18:00 clinic time.
- Same-day reminder 3 hours before the appointment, only inside 09:00–20:00.
- Review request at 10:00 the next day, only for appointments marked attended.
- Respect the approved `No recibir más` quick reply.
- A `Confirmar` tap writes Dentalink status `Confirmado por pcte. vía WhatsApp`
  (clinic status ID `22`, confirmed by the user after a live metadata-only check).
- A `Cancelar` tap still requires a second explicit confirmation before cancellation.
- Keep production recipients blocked behind an off-by-default feature flag and explicit
  phone allowlist.

## Approved templates

- `recordatorio_turno_confirmar` (`es_AR`, UTILITY): Confirmar / Cancelar.
- `recordatorio_turno_ubicacion` (`es_AR`, UTILITY): Cómo llegar.
- `solicitud_resena_google` (`es_AR`, MARKETING): Opinar / No recibir más.

## Scope

- YCloud template-send transport and template quick-reply webhook parsing.
- Dentalink appointment/patient read support and explicit clinic status semantics.
- Durable, idempotent reminder scheduling and delivery with retries and observability.
- Deterministic reminder button handling, including stale/duplicate protection and
  review opt-out.
- Safe configuration, dependency wiring, worker lifecycle, and operator docs.

## Non-goals

- Sending to any non-allowlisted patient during staged rollout.
- Inferring that a patient completed a Google review after opening the URL.
- Incentives, review gating, sentiment filtering, or selective review solicitation.
- Push, pull request creation, merge, or production deployment.

## Constraints

- Hexagonal boundaries and existing repository conventions.
- Test-first for deterministic behavior: observed RED, GREEN, then refactor.
- Preserve unrelated work in `/home/lucy/work/agente-ai`; all writes occur in this
  isolated worktree.
- No reminder sends unless both the feature flag and recipient allowlist permit them.
- Idempotency is appointment + reminder kind; retries must not duplicate completed
  sends.
- Appointment state is revalidated immediately before every send or state mutation.

## Tasks

- [x] T1 — Add YCloud template transport and parse template quick-reply callbacks;
  include off-by-default reminder settings and allowlist validation.
- [x] T2 — Add Dentalink date-window appointment reads, patient lookup, and explicit
  confirmed/attended/cancelled status resolution from clinic metadata.
- [x] T3 — Add durable reminder persistence, scheduler, claim/retry behavior, and
  allowlisted template delivery for the three timing rules.
- [ ] T4 — Handle Confirmar, Cancelar, Cómo llegar, and No recibir más payloads with
  stale/duplicate safeguards and durable opt-out.
- [ ] T5 — Wire the disabled-by-default worker, add operational observability/docs,
  and run focused plus full verification without a live patient send.

## Acceptance criteria

- With defaults, no reminder is sent.
- With reminders enabled but an empty allowlist, no reminder is sent.
- Only allowlisted numbers can receive staged reminders.
- Confirmation reminders are sent at most once per appointment/kind and use the
  approved `es_AR` templates with correct parameters.
- Same-day reminders are skipped when their due time is outside 09:00–20:00.
- Review requests go only to attended appointments and are rate-limited to once per
  patient per 90 days.
- Cancelled/no-show appointments never receive a review request.
- Button payloads are deterministic and cannot mutate another patient's appointment.
- Opted-out patients receive no later review requests.
- Failures are visible and retryable without duplicate completed sends.

## Checks

- Per task: focused `uv run pytest ...` through a verifier.
- Final: `uv run pytest`, `uv run ruff check .`, `uv run mypy app/` through a verifier.
- Structural review of migrations, configuration defaults, and operator docs.
- No live YCloud send until the owner supplies/approves the recipient test number.

## Delivery

- Branch: `feat/appointment-reminders` from `origin/main` at `ba18fdb`.
- Worktree: `/home/lucy/work/agente-ai-worktrees/appointment-reminders`.
- Forecast: approximately 850–1,500 authored lines plus tests/migration, above the
  400-line review budget.
- Strategy: five work-unit commits; defer PR slicing decision until actual diff size
  is known. Push/PR/merge remain user decisions.

## Routes

- T1–T5: one bounded `gentle-ai-worker` at a time because each touches multiple
  non-trivial files.
- Every verification command: `gentle-ai-verify`.

## Progress

- Exploration and product decision complete.
- Isolated worktree created from `origin/main`.
- T1 complete: template transport, actual template-button callback parsing, safe
  settings, and fake compatibility. Verification: 131 focused tests passed; ruff,
  mypy, and `git diff --check` passed. Work-unit commit: `7fd0765`. Native review
  was unavailable (`package-local-binary-missing`). Live YCloud send intentionally
  deferred.
- T2 complete: conservative Dentalink reminder states and bounded date-window/patient
  reads. Verification: 171 Dentalink tests passed; ruff, mypy, and diff check passed.
  Work-unit commits: `cb1ff28`, `67d4992`. Live response metadata remains unverified;
  unknown states fail closed.
- T3 complete: timing planner, migration/model, atomic repository, allowlisted
  scheduling, configured template construction, state-revalidated delivery, lease
  renewal, and bounded retries. Work-unit commits: `97f688d`, `6e01837`, `e491abe`,
  `eb029fa`, `caa42b9`, `c8abc25`, `e0b7ec8`, plus the worker/config commit recorded
  with this progress update. Verification: 243 focused tests passed; ruff, mypy,
  Alembic single-head, and diff checks passed. Provider exactly-once remains impossible
  only for a crash after YCloud accepts a send and before the DB terminal write.

## Next step

T4.
