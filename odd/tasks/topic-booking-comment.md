# Topic booking comment

## Objective

Every appointment booked from "Consultas frecuentes" goes to the Dentalink specialty "General" and
carries, in the appointment comment, the topic the patient chose, so administration knows what the
appointment is about: Blanqueamiento, Consulta Particular, Limpieza Particular, Brackets por obra
social, Alineadores (with the chosen option for Alineadores).

## Problem

- Blanqueamiento, limpieza and brackets did not preselect General (only consulta particular and
  alineadores did), so after identification the patient saw the specialty list (live report).
- All of them end up as plain "General" appointments: administration cannot tell a blanqueamiento
  from a consulta particular.
- The agent never sends a comment to Dentalink: `AppointmentGateway.create_appointment` has no
  comment parameter.

## Dentalink facts (from api.dentalink.healthatom.com/docs, 2026-10-02)

- `POST /citas/` example body uses `comentario` (singular); the response carries `comentarios`
  (plural).
- `PUT /citas/{id_cita}` takes `comentarios` (plural) in its body ("modificar estado, duración y
  comentario").
- The docs are inconsistent and we cannot test against a live account here, so the create call
  must verify and, if needed, complete the comment: send `comentario` on POST, read `comentarios`
  from the response, and if it does not hold the text, `PUT /v1/citas/{id}` with `comentarios`.
  A failure of that completion is logged and never fails or rolls back the booking.

## Scope

- T1: limpieza_particular and brackets_obra_social also preselect "General" (all five topics book
  General; alineadores keeps its three options).
- T2: carry the chosen topic (and the alineadores option) through the booking flow until the
  confirmation: set when the patient taps the topic's "Agendar cita" (`FAQ_BOOK:<topic>`) or an
  alineadores option (`FAQ_OPTION:alineadores:<n>`) or books a topic by free text; survives the
  first-visit question, identification and slot selection; dropped on cancel/reschedule/view and on
  the main-menu reset; never reused by a later unrelated booking.
- T3: send it as the appointment comment: proposal payload -> confirmation -> create use cases ->
  `AppointmentGateway.create_appointment(..., comment=...)` -> Dentalink create with the
  verify-and-complete logic above. Comment text: `Consulta frecuente: <label>` and, for
  alineadores, `Consulta frecuente: Alineadores - Opción <n>`; labels exactly: Blanqueamiento,
  Consulta Particular, Limpieza Particular, Brackets por obra social, Alineadores.
- Out of scope: reschedule keeps whatever comment the appointment already has.

## Constraints

- Branch `feat/topic-booking-comment` from origin/main (23c4976, v0.48.1), worktree
  `../agente-ai-worktrees/blanqueamiento-general`. Commit 0fd62d2 (blanqueamiento -> General) is
  already on it.
- Strict TDD. Runner: `uv run pytest`; also `uv run ruff check .`, `uv run mypy app/`,
  `uv run ruff format --check <changed files>`.
- Known environmental failures: `tests/integration/test_redis_debounce_lock.py` (3).
- English artifacts, Spanish patient copy, no AI attribution in commits.
- Delivery: `docs/pr-release-workflow.md`, `feat(...)` title (minor release).

## Tasks

- [x] T1 — all five topics preselect General. Commit 227f78f. RED: 8 failures (mapping, buttons, router, free text) before the change; GREEN after.
- [x] T2 — carry the chosen topic until the confirmation. Commit 49d2eea. RED: collection ImportError (`BOOKING_TOPIC_KEY`, `booking_comment` missing); GREEN: 35 tests.
- [x] T3 — send the topic as the Dentalink appointment comment (verify and complete). Commit b2ebc8f. RED: 16 failures (gateway, fake, use cases, node e2e) before the change; GREEN after.

## Acceptance criteria

- Tapping "Agendar cita" on any topic (or an alineadores option) leads, after the first-visit
  question and identification, straight to the slots of General.
- The created appointment carries `Consulta frecuente: <label>` in its comment, also when Dentalink
  ignores the field on create (completed with a PUT); a comment failure never fails the booking.
- A booking that did not start from a topic carries no comment.

## Progress

- Worktree and branch ready (2026-10-02); T1 partly done by 0fd62d2 (blanqueamiento).
- T1-T3 done (227f78f, 49d2eea, b2ebc8f). Route: delegated direct, single writer. TDD strict, runner `uv run pytest`.
- Comment travels in the pending-action payload (`comment`, only when a topic was chosen).

## Next step

Review, then PR per `docs/pr-release-workflow.md` (user decision; nothing pushed).
