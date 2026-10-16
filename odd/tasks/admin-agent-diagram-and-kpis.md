# Admin panel: one live agent diagram + KPI dashboard with PDF export

Status: Track A in progress on branch `feat/admin-agent-diagram` (started 2026-10-16). Track B waits for real bot data: nothing is connected yet, so the B1 audit is postponed. The full plan lives outside the repo at `~/.claude/plans/el-dise-o-de-la-joyful-waffle.md`; this document is the durable summary.

## Objective
(a) Replace the per-run Mermaid charts with **one** interactive diagram that cycles through the agent's graphs and shows each one's state. (b) Add a KPI dashboard (appointments taken by the bot, appointments cancelled, most-booked) with a button that exports a well formatted PDF with charts.

## Problem
- `conversation-detail.html` and `run-detail.html` draw one hand-written Mermaid flowchart per agent run, so charts multiply. The topology in `app/static/admin/graph-view.js` is stale versus `app/agent/graph.py` (missing `faq_topic`, `payment_admin`, `reminder_action` and several edges).
- Nothing is streamed: pages poll every 10 s and a turn's trace is committed only when the turn ends.
- The panel has no aggregates, no dashboard and no export (no `func.`/`group_by` in `app/application/admin/*`).

## Decisions made with the user
- "Real time" = frequent polling (about every 5 s) of per-node aggregated state from existing data. No change to the agent core.
- Subgraph nodes (appointment decision, first-visit intake) are shown as structure only. Verified: `_traced` in `app/agent/appointment_decision_subgraph.py` only logs; `node_executions` rows come only from `with_error_handling` (13 wrapped nodes in `app/agent/graph.py`).
- KPIs are computed only from what the bot stores, never from Dentalink.
- PDF = browser print to PDF from a print-designed A4 page (no new server libraries).
- Inspiration only, no dependency: `cathrynlavery/diagram-design` (MIT, visual language: tokens, 1 px hairlines, 4 px grid) and `tt-a1i/archify` (MIT, interaction model: focus, route highlight, legend, hash state). Only their README pages were read.

## Track A: single diagram at `/admin/agent`
- Tabs Principal, Decisión de turno, Primera visita; auto-cycle about every 8 s with pause on hover/focus and when the tab is hidden; Prev/Next; keyboard; URL hash state; `prefers-reduced-motion` turns auto-cycle off; run mode `#run=<id>` replaces the per-run charts.
- Backend: `GET /admin/api/graphs` (topology from `build_*().get_graph()`, drift guard test) and `GET /admin/api/graphs/state?window=15m|1h|24h` (per node count, failed, running, last status, avg/p50 duration, last error and run). New `list_since(since)` on `NodeExecutionRepository` (SQL and fake).
- Frontend: custom inline SVG with a small layered layout, laid out once per graph and patched on each poll; reuse the existing dark palette and `ADMIN` helpers; delete `graph-view.js` and the Mermaid CDN script at the end.

## Track B: KPIs + PDF at `/admin/kpis`
- Data in the bot's DB (verified): no local appointments table in use; bookings are `pending_actions` rows (`create_appointment`, `reschedule_appointment`, `cancel_appointment`; payload has `slot_start`, `professional_id`, `specialty_id`, `patient_id`). `confirmed` is NOT proof of a booking (status flips before the Dentalink call, `executed_at` is never written); success is evidenced by `tool_executions` (`CreateAppointmentTool` / `cancel_appointment` completed). Staff cancellations in Dentalink leave no trace, so cancellations are "vía bot" only. Specialty may be empty and only ids are stored. The admin conversation reset deletes tool evidence but keeps `pending_actions`. Test and real numbers are not distinguishable. Clinic timezone `America/Argentina/Buenos_Aires`.
- KPI rules (to fix in B1 against real data): taken = confirmed `create_appointment` by `confirmed_at`, cross-checked with tool evidence and showing how many lack it; reschedules separate; cancelled = confirmed `cancel_appointment`, labeled "vía bot"; most-booked = top professional, specialty ("Sin especialidad" for empty), weekday and hour of `slot_start` in clinic time. Period 7/30/90 days or custom, default 30. Every view and the PDF say "Datos registrados por el bot; no incluye turnos cargados o cancelados directamente en Dentalink".
- Backend: `GET /admin/api/kpis?from=&to=`, new `kpi_queries.py`, repository window queries with fakes, aggregation in Python with a row cap.
- Frontend: KPI cards, inline-SVG charts (per-day taken vs cancelled, top bars, weekday x hour strip), `@media print` A4 layout with header, footer and light theme, and an "Exportar PDF" button calling `window.print()`.

## Tasks
- [x] 1 Design artifact of both pages (including the A4 print layout). Evidence: user approved on 2026-10-16 (private canvas https://claude.ai/artifact/J8StXB1tvRuHtfocnuhLio; source files kept in the session scratchpad). Prototype simplifies handle_error/Fin arrows and two sibling edges; the real page draws all edges.
- [ ] 2 B1 data audit: read-only SQL the user runs on production (confirmed create rows vs completed tool executions, empty specialties, test contacts) to fix the KPI rules.
- [x] 3 A1 topology endpoint + drift guard test. Evidence: commit 4fa71dd, delegated writer, tests and lint green; assess medium, under_budget.
- [x] 4 A2 node execution window query (Protocol, SQL, fake) + tests. Evidence: unit 3687 passed (3 known failures), mypy and ruff clean; SQL integration test collects but skipped (no DB); RED not observed (tests and code written in one pass). Finding: RUNNING rows are flushed, not committed, until the turn ends (`repositories.py:327`), so the diagram shows finished turns only.
- [x] 5 A3 graph state endpoint + role/window tests. Evidence: unit 3699 passed (3 known failures), mypy and ruff clean, RED observed (import errors); also fixed A2 review notes (exact `truncated`, 422 on bad window). A1+A2 slice reviewed and approved by native review (reliability lens).
- [x] 6 A4 agent diagram page. Evidence: unit 3701 passed (3 known failures), mypy/ruff/node --check clean; real headless Chromium against a stub API: 3 graphs render, 0 node overlaps, detail panel and error banner work. Not verified: real app/DB, light theme, mobile width, Firefox/Safari. No RED (page test written with the code).
- [x] 7 A5 cycling, keyboard, hash, reduced motion. Evidence: unit 3701 passed (3 known failures), mypy/ruff/node --check clean; pure helpers pass a Node script; real headless Chromium over CDP: real 8 s cycle, hover/focus pause, manual pause, node pin, arrows/Space/Enter/Esc, hash round-trip and hostile values, reduced motion. Not verified: real hidden tab (simulated), real app, Firefox/Safari, mobile, light theme. A6 must preserve `#run=` in the hash.
- [x] 8 A6 replace per-run Mermaid with run overlay; remove Mermaid and `graph-view.js`. Evidence: unit 3704 passed (3 known failures), mypy/ruff/node --check clean; Node unit script for run-mode logic; headless Chromium against a stub API (run banner, node states, invalid ids, back to live, detail pages without Mermaid). Not verified: real backend, a real in-flight run, subgraph tabs in run mode (only `main` has traced nodes), mobile, light theme, Firefox/Safari.
- [ ] 9 B2 KPI queries (repositories, fakes, timezone aggregation) + tests.
- [ ] 10 B3 KPIs endpoint + role/range/empty tests.
- [ ] 11 B4 KPI dashboard page.
- [ ] 12 B5 print layout and PDF export button.
- [ ] 13 Docs.

## Acceptance criteria
- One diagram page that cycles through the three graphs, shows aggregated per-node state, updates every few seconds without nodes jumping, and is keyboard operable; no per-run Mermaid copies remain.
- KPI page with taken, cancelled (via bot) and most-booked, an on-screen and in-PDF scope note, and a PDF export that looks right on A4 in Chrome.
- Tests for every new endpoint (all three roles 200, anonymous 401, bad parameters 422) and the aggregations; `uv run pytest tests/unit`, `ruff check` and `mypy app` green except the 3 known failures in `tests/unit/api/dependencies/test_gateway_dependency.py`.

## Risks (ranked)
1. KPI truthfulness (confirmed is not booked, resets erase evidence, staff cancels invisible). 2. Test data mixed with real data; may need a contact exclusion list. 3. "Live" limited by when the `RUNNING` row is committed. 4. Subgraph nodes have no state in v1. 5. No indexes on the time columns; row caps and maybe an index migration. 6. Top-list names need catalog calls with id fallback. 7. `get_graph()` may need a small factory refactor. 8. Layout and print fidelity vary by browser. 9. Default of auto-cycle is open.

## Next step
Create the Design artifact (task 1) once the user is ready, then B1 audit queries.
