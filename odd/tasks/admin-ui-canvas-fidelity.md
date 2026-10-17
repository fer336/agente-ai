# admin-ui-canvas-fidelity

## Objective
The admin pages (`/admin/agent`, `/admin/kpis`, `/admin/agent-control`, the pause banner and the rest of the shell) must look like the approved Claude Design canvas (`Main.dc.html`, `Kpis.dc.html`, `KpisPrint.dc.html`), not loosely follow it.

## Problem
1. Agent diagram wider than its container at 1363px; page-level horizontal scroll; canvas composition not reproduced.
2. Header/nav differ (canvas: title + subtitle left, nav with accent underline right, one row).
3. Pause banner link dark blue on brown (illegible).
4. Stale `style.css` in the browser: no `Cache-Control` on `/admin/static`.
5. KPI page and A4 print drift from the canvas.

## Constraints
Plain HTML/JS/CSS, no build step. UI copy Spanish; code/comments/commits English. Bot-only role serves no admin static. Local-only: no push, no PR, no external calls.

## Tasks
- [x] T1 Cache revalidation for admin static files and pages (+ unit tests)
- [ ] T2 Shared shell (header/nav, buttons, tab groups, cards, legible pause banner)
- [ ] T3 Agent diagram: canvas composition and measures, scroll inside container
- [ ] T4 KPI page + A4 print match canvas; PDF verified with Chromium
- [ ] T5 Control page and banner in the same visual language

## Acceptance
Visual comparison against the canvas at 1363x691, 1440x900, 1024x768, 390x844; unit tests, ruff, mypy green; node --check on touched JS.

## Evidence / progress
- T1: `RevalidatingStaticFiles` + `_page()` in admin_pages.py (Cache-Control: no-cache, ETag, 304 keeps header). pytest test_admin_pages + test_app_roles: 50 passed.
