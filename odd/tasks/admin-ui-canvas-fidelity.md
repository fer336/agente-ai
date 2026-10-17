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
- [x] T2 Shared shell (header/nav, buttons, tab groups, cards, legible pause banner)
- [x] T3 Agent diagram: canvas composition and measures, scroll inside container
- [x] T4 KPI page + A4 print match canvas; PDF verified with Chromium
- [x] T5 (banner + control; control verified visually, active/paused/390px) Control page and banner in the same visual language

## Acceptance
Visual comparison against the canvas at 1363x691, 1440x900, 1024x768, 390x844; unit tests, ruff, mypy green; node --check on touched JS.

## Evidence / progress
- T1: `RevalidatingStaticFiles` + `_page()` in admin_pages.py (Cache-Control: no-cache, ETag, 304 keeps header). pytest test_admin_pages + test_app_roles: 50 passed.
- T2: header = title+subtitle left, nav (accent underline) + user/logout right on all pages; canvas tokens in `style.css`; banner strip at top, link #8bb2ff on #2f2818 = 6.9:1, drawn from a sessionStorage hint to avoid layout shift. Screens: scratchpad shots_ui/t2_*, t5_*.
- T3: `canvasPlan` + `computeCanvasLayout` reproduce Main.dc.html (1208x520, boxes 176x64 / 112x96, pill, 191x64 dashed error + "N errores en la ventana", Fin bar); generic layered layout kept for the other graphs with the same measures; stage scrolls inside its panel; scales to fit only when within 92%. Screens: shots_ui/t3_*. No page-level h-scroll at 1363/1440/1250/1024/390.
- T4: KPI screen follows Kpis.dc.html (toolbar row with Exportar PDF 44px, "16 sep 2026" dates, axis 11px, bare heat grid/tables inside panels); print follows KpisPrint.dc.html (48px page margin, short card labels, "Período: 16 sep al 15 oct 2026", "Generado: 15 oct 2026, 11:30", footer pinned to the bottom). Chromium printToPDF: 1 page A4 (595x842 pt) for ok, wide, trunc and empty samples; min font 9 pt (12 px).
- Deviations: stage left-aligned like the canvas; edges between leaves (reminder_action->appointment->handoff) not drawn (canvas omits them, listed in node detail); no "Ver en subgrafos" link (no subgraph data); edges all solid; 16px gutter below 640px; extra nav item "Control" and user/logout under the nav; "Actualizar" button and updated time kept on KPIs.
