# Clinic topics FAQ

## Objective

Answer the clinic's 5 frequent topics (blanqueamiento, consulta particular, limpieza particular,
brackets por obra social, alineadores) and the OSDE / Medifé / William Hope first-visit case with
fixed clinic-authored text, reachable from the main menu and from free text.

## Problem

~90% of the clinic's inquiries are about those topics. The agent has no price/FAQ knowledge:
`question.py` depends on the `understand()` LLM answer, so prices could be invented.

## Scope

- Texts live as code constants (user decision), in one module, easy to edit.
- Source of the content: clinic WhatsApp screenshot (2026-09-30). Only two figures are stated and
  they are confirmed by the owner: consulta particular $60.000 and blanqueamiento $450.000 (no
  promo). The other topics carry no prices; administration confirms them.
- OSDE / Medifé / William Hope text is final (clinic version of 16:02).

## Constraints

- Branch `feat/clinic-topics-faq` from origin/main (ab57678), worktree
  `../agente-ai-worktrees/clinic-topics-faq`.
- Strict TDD (RED -> GREEN -> REFACTOR). Runner: `uv run pytest`; also `uv run ruff check .`,
  `uv run mypy app/`, `uv run ruff format --check <changed files>`.
- Known environmental failures: `tests/integration/test_redis_debounce_lock.py` (3).
- English artifacts, Spanish patient copy, no AI attribution in commits.
- ~400 authored changed lines per task is a planning heuristic only.
- Delivery: `docs/pr-release-workflow.md`, `feat(...)` title (minor release).
- Plan: `/home/lucy/.claude/plans/merry-sniffing-kurzweil.md`.

## Tasks

- [x] T1 — Content module `app/agent/clinic_topics.py` + `faq_topic` node + routing (payloads,
  deterministic keyword pre-check, not in data-collection stages) + graph wiring + understand
  prompt/fake keywords. Route: delegated direct (writer trigger).
- [x] T2 — Menu: `ℹ️ Consultas frecuentes` row + 5-row sub-list; update menu tests; add a
  `ListMessage` 10-row validation. Route: delegated direct.
- [x] T3 — Special insurances fixed text in `agreement.py` (precedence vs "cuánto cubre" derive),
  eval dataset `evals/datasets/clinic_topics.yaml` + replay registration, PRD §7 update.
  Route: delegated direct.
- [x] T4 — Book a consulta particular on the Dentalink specialty "General": `FAQ_BOOK:<topic>`
  payload + `ClinicTopic.book_specialty`, router preselection (button idle/mid-flow and free
  text), subgraph consumes the one-shot `preselected_specialty_name` (exact accent-insensitive
  match, fallback to the list), eval seed "General" + replay scenario. Commit f8b2ddf. Route:
  delegated direct (single writer).
- [x] T5 — Location answer with the clinic image: a location question (free text, the menu
  row, or after a finished booking) sends `app/static/public/clinic-location.jpg` (served by this
  app under `/public`) with a caption and one `Cómo llegar` button (`LOCATION_DETAIL`); tapping it
  returns the native location card. `response_image_url` in the state, `create_location_node(image_url)`,
  settings `public_base_url` / `location_image_url`, eval stack `image_url`, dataset
  `evals/datasets/location.yaml`. Commit c099a60. Route: delegated direct (single writer).

- [x] T6 — Alineadores answer = clinic image + 3 buttons (Opción 1/2/3); each option starts the
  booking (first-visit question first, then straight to the General specialty) and the chosen option
  is remembered and shown in the confirmation. Route: delegated direct.
- [x] T7 — Payment, advance and installment questions get "se manejan directamente con
  Administración" (deterministic detector + LLM-worded answer + question-node backstop).
  Route: delegated direct.
- [ ] T8 — OSDE / Medifé / William Hope answer written by the LLM each time, facts guarded by a
  validator with the fixed text as fallback. Route: delegated direct.

## Acceptance criteria

- Each topic returns its exact fixed text with Agendar / Menú principal / Asesor buttons.
- Free text and menu taps reach the node; a mid-booking question keeps the stage.
- Typing "OSDE" in intake/identification stays data.
- "¿Cuánto cubre OSDE?" still defers to administración.

## Progress

- Worktree created (2026-10-01).
- T1 done, commit 42c0be2 (route: delegated direct). RED: new test modules failed at collection
  (no `app.agent.clinic_topics`, no `FAQ_TOPIC_NODE`) and 15 resolve/LLM tests failed. GREEN:
  `uv run pytest` 2322 passed, 83 skipped, only the 3 known redis_debounce_lock failures;
  `ruff check .` clean; `mypy app/` clean. Changed `test_internal_eval_real_llm.py` message to
  "quiero un turno" (the old "limpieza" text is now answered by the deterministic pre-check
  before the LLM). `MENU_FAQ_PAYLOAD` is defined but not routed (sub-list is T2).

- T1 follow-up, commit 8b26d0f: a booking request naming a topic ("turno para limpieza") skips
  the fixed answer (`_asks_to_book` guard; fake LLM and understand prompt aligned). RED: 3 new
  tests failed; GREEN: 2325 passed, only the 3 known redis failures; ruff and mypy clean.

- T2 done, commit 0f7f3d7 (route: delegated direct). RED: 11 new tests failed (no menu row, no
  sub-list, no 10-row validation). GREEN: `uv run pytest` 2337 passed, only the 3 known redis
  failures; `ruff check .` and `mypy app/` clean. MENU_FAQ routes to `faq_topic` via
  `_GLOBAL_BUTTON_INTENTS`; the node returns the 5-row list when `button_payload == MENU_FAQ`.
  `ListMessage` caps rows at 10 (`MAX_LIST_ROWS`, reused by `paginated_list.MAX_ROWS`); all
  existing lists go through `paginate_rows` (max 10) or are fixed menus (7 / 5 rows). PRD §7 updated.

- T3 done, commit 3b68a8c (route: delegated direct). RED: 7 agreement-node tests failed (no special
  text, coverage questions about Medife/William Hope fell to not_found), 3 fake-LLM tests failed
  (Medife / William Hope not classified as insurance) and the `clinic_topics` replay failed
  (Medife / William Hope never reached `agreement`). GREEN: `uv run pytest` 2363 passed, only
  the 3 known redis_debounce_lock failures; `ruff check .` and `mypy app/` clean. The agreement
  node sends no buttons today for a found agreement, so the special text has none either.
  Intake/identification/new-patient-details regression tests cover medife / william hope.
  PRD section 7 was already updated in T2. Pre-existing unformatted lines in agreement.py and
  two test files were left untouched.

- Native review (high, 31 files, 1462 lines, 4 lenses): consent granted, approved and
  acknowledged (lineage review-17fb8cffe48f78bb). Advisory, non-blocking: R2-1 menu_payloads
  readability, R2-2 faq_topic, R2-3 clinic_topics, R4 unconfirmed prices (TODO(clinic)).

- T4 done, commit f8b2ddf (route: delegated direct). RED: both new test modules failed at
  collection (no `PRESELECTED_SPECIALTY_KEY`, no `faq_book_payload`) and the new seed test failed
  (KeyError "General"). GREEN: `uv run pytest` 2411 passed, only the 3 known redis_debounce_lock
  failures (plus their 3 setup errors); `ruff check .` and `mypy app/` clean. The key is consumed
  in the decision subgraph's `choose_specialty` (no options yet), after the first-visit question
  and identification. Free-text preselection applies only with no active stage (nothing would
  consume it mid-flow). Added keywords "turno particular" / "cita particular" to the topic.

- Native review of T4 + phrasing fix (medium, 14 files, 902 lines, 1 consolidated lens): consent
  granted, approved and acknowledged (lineage review-a0d1416822f76fe5). Advisory: R3-1 the
  unresolved-topic path now shows the topic list instead of a handoff offer (intended, no other
  caller depended on it); R3-2 the slot-search exception branch of the preselected offer has no
  test that makes the gateway raise (follow-up).

- T5 done, commit c099a60 (route: delegated direct). RED: new node/resolve/settings/invoker/static
  tests failed at collection (no `LOCATION_DETAIL_PAYLOAD`), then 46 unit tests failed with the
  payload alone (invoker `location_image_url`, node factory, settings property, mount, eval
  `image_url`). GREEN: `uv run pytest` 2434 passed, only the 3 known redis_debounce_lock failures
  (plus their 3 setup errors); `ruff check .` and `mypy app/` clean. With no image URL configured
  the node falls back to the native card. The post-booking location question is proven both at
  the router (`post_action_context` set) and end to end (invoker and eval dataset).

- Native review of T5 (high, 32 files, 686 lines, 4 lenses): consent granted, approved and
  acknowledged (lineage review-37a1ed3a76139bc5). Advisory: R3-001/R4-001 an unreachable image
  left the patient with no location reply -> fixed in the follow-up commit (`SendReplyUseCase`
  resends the buttons without the image when the image send fails; RED: 1 failing test, GREEN:
  2436 passed, only the 3 known redis failures). R2-1 caption repeats the address (follow-up),
  R2-2 `public_base_url` defaults to the production host (documented in the env template).

## Next step

Push, issue and PR (user decision): `feat(...)` title per `docs/pr-release-workflow.md`.

- Prices (owner decision 2026-10-01): only consulta particular ($60.000) and blanqueamiento
  ($450.000, promo dropped) state figures; alineadores, limpieza and brackets state none. The
  Dentalink specialty is confirmed to be named "General". RED: 2 tests failed; GREEN: 2437 passed,
  only the 3 known redis failures; ruff and mypy clean.

- T6 done, commit cdabf0c (route: delegated direct). RED: the new `test_faq_option.py` failed at
  collection (no `ALIGNER_OPTION_KEY`, `faq_option_payload`). GREEN: `uv run pytest` 2468 passed,
  only the 3 known redis_debounce_lock failures (plus their 3 setup errors); `ruff check .` and
  `mypy app/` clean. `ALIGNERS_IMAGE_URL` / `effective_aligners_image_url` reach the `faq_topic`
  node like the location URL; the options replace the Agendar/Menú/Administración trio; the
  confirmation shows "Consulta por alineadores: Opción n" and nothing is sent to Dentalink.

- T7 done, commit 8fd84d0 (route: delegated direct). RED: the detector and node test modules failed
  at collection (no `app.agent.payment_questions`, no `nodes.payment_admin`), plus router, graph,
  question-backstop, fake-LLM and prompt tests. GREEN: `uv run pytest` 2512 passed, only the 3 known
  redis_debounce_lock failures (plus their 3 setup errors); `ruff check .` and `mypy app/` clean.
  Payment terms win over a topic keyword except alineadores; not applied in data stages; backstop in
  `question.py` and `fallback.py`; understand prompt no longer lists payments under `faq_topic` or as
  a free `question` answer; dataset got 3 deterministic cases and 1 real-LLM case; PRD scope rule added.
