// KPIs page (/admin/kpis). Plain JS, no build step, no chart library: every
// chart is inline SVG/HTML drawn by small pure functions (exported for Node,
// see the bottom of the file). Data comes from GET /admin/api/kpis. There is
// no polling: the page loads on open, on period change and on the manual
// "Actualizar" button.
//
// Every label shown comes from either a fixed Spanish string or an external
// system (Dentalink professional/specialty names) and is escaped before it is
// put into HTML. Hash values are validated strictly and never reach the DOM.

const Kpis = (() => {
  const MAX_RANGE_DAYS = 366; // mirrors the API's limit
  const PRESETS = [7, 30, 90];
  const DEFAULT_DAYS = 30;
  const WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
  const HEAT_HOURS_MIN = 8; // default visible hour range; widened if data falls outside
  const HEAT_HOURS_MAX = 19;
  const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

  // ---------------------------------------------------------------- dates

  // Strict calendar check: shape AND a real date (2026-02-30 is rejected).
  function isIsoDate(value) {
    if (typeof value !== "string") return false;
    const m = ISO_RE.exec(value);
    if (!m) return false;
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
  }

  function toUtcMs(iso) {
    const m = ISO_RE.exec(iso);
    return Date.UTC(+m[1], +m[2] - 1, +m[3]);
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function fromUtcMs(ms) {
    const d = new Date(ms);
    return `${String(d.getUTCFullYear()).padStart(4, "0")}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
  }

  function addDays(iso, days) {
    return fromUtcMs(toUtcMs(iso) + days * 86400000);
  }

  // Inclusive number of days in [from, to].
  function daysInRange(from, to) {
    return Math.round((toUtcMs(to) - toUtcMs(from)) / 86400000) + 1;
  }

  // The browser's local calendar date; only used until the API tells us the
  // clinic's own "today" (the `period.date_to` echo of a request without `to`).
  function browserToday(now = new Date()) {
    return `${String(now.getFullYear()).padStart(4, "0")}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
  }

  // Returns an error message (Spanish, user-facing) or null when valid.
  function validateRange(from, to) {
    if (!isIsoDate(from) || !isIsoDate(to)) return "Ingresá fechas válidas.";
    if (from > to) return "La fecha inicial no puede ser posterior a la final.";
    if (daysInRange(from, to) > MAX_RANGE_DAYS) return `El período no puede superar los ${MAX_RANGE_DAYS} días.`;
    return null;
  }

  function presetRange(days, today) {
    return { from: addDays(today, -(days - 1)), to: today };
  }

  // Which segmented button is pressed: a preset when the range ends today and
  // spans exactly 7/30/90 days, otherwise "custom".
  function detectPreset(range, today) {
    if (!range || range.to !== today) return "custom";
    const days = daysInRange(range.from, range.to);
    return PRESETS.includes(days) ? String(days) : "custom";
  }

  // ------------------------------------------------------------- URL hash

  // `#from=YYYY-MM-DD&to=YYYY-MM-DD`. Anything invalid (shape, calendar,
  // order, span, missing half) yields null so the caller falls back to the
  // default period. Values are never returned unless they passed validation.
  function parseHash(hash) {
    const params = new URLSearchParams(String(hash || "").replace(/^#/, ""));
    const from = params.get("from");
    const to = params.get("to");
    if (from === null || to === null) return null;
    if (validateRange(from, to) !== null) return null;
    return { from, to };
  }

  function serializeHash(range) {
    if (!range || validateRange(range.from, range.to) !== null) return "";
    return `#from=${range.from}&to=${range.to}`;
  }

  // ------------------------------------------------------------ formatting

  // es-AR: dot thousands, comma decimals. Hand-rolled so it is identical in
  // every browser/ICU build (and in Node tests).
  function groupThousands(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }

  function fmtInt(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    const rounded = Math.round(n);
    return (rounded < 0 ? "-" : "") + groupThousands(String(Math.abs(rounded)));
  }

  // 14 -> "14 %", 12.5 -> "12,5 %", 1234.5 -> "1.234,5 %".
  function fmtPct(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    const abs = Math.abs(Math.round(n * 10) / 10);
    const [int, dec] = String(abs).split(".");
    return `${n < 0 && abs !== 0 ? "-" : ""}${groupThousands(int)}${dec ? "," + dec : ""} %`;
  }

  // "2026-09-16" -> "16/09/2026"
  function fmtDate(iso) {
    if (!isIsoDate(iso)) return "—";
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
  }

  const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  // Short axis label: "16 sep"
  function fmtDayMonth(iso) {
    return isIsoDate(iso) ? `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}` : "";
  }

  // "2026-09-16" -> "16 sep 2026"
  function fmtDateLong(iso) {
    return isIsoDate(iso) ? `${fmtDayMonth(iso)} ${iso.slice(0, 4)}` : "—";
  }

  // One KPI card's comparison line. `change_pct` is null when the previous
  // period had zero; direction is carried by the arrow, never by color alone.
  function describeChange(total) {
    const previous = total.previous;
    const pct = total.change_pct;
    if (pct === null || pct === undefined) {
      return { dir: "none", text: `Sin dato comparable (período anterior: ${fmtInt(previous)})`, print: `Sin dato comparable (antes ${fmtInt(previous)})` };
    }
    if (pct > 0) return { dir: "up", text: `▲ ${fmtPct(pct)} más que el período anterior (${fmtInt(previous)})`, print: `▲ ${fmtPct(pct)} (antes ${fmtInt(previous)})` };
    if (pct < 0) return { dir: "down", text: `▼ ${fmtPct(Math.abs(pct))} menos que el período anterior (${fmtInt(previous)})`, print: `▼ ${fmtPct(Math.abs(pct))} (antes ${fmtInt(previous)})` };
    return { dir: "flat", text: `= Igual que el período anterior (${fmtInt(previous)})`, print: `= Igual (antes ${fmtInt(previous)})` };
  }

  // ------------------------------------------------------- chart geometry

  // Integer y-axis ticks with at most 4 intervals: step in 1, 2, 5, 10, 20, 50...
  function niceScale(max) {
    const m = Math.max(1, Math.ceil(Number(max) || 0));
    let step = 1;
    const mult = [1, 2, 5];
    for (let i = 0; Math.ceil(m / step) > 4; i++) {
      step = mult[i % 3] * Math.pow(10, Math.floor(i / 3));
    }
    const top = Math.max(step, Math.ceil(m / step) * step);
    const ticks = [];
    for (let v = 0; v <= top; v += step) ticks.push(v);
    return { top, step, ticks };
  }

  const CHART_BOX = { width: 800, height: 210, left: 40, right: 40, top: 20, bottom: 30 };

  // Points for the per-day series. x is spread evenly (a single day sits in
  // the middle); y is scaled to a nice integer axis. Rounded to 1 decimal.
  function seriesGeometry(perDay, box = CHART_BOX) {
    const days = Array.isArray(perDay) ? perDay : [];
    const plotW = box.width - box.left - box.right;
    const plotH = box.height - box.top - box.bottom;
    const baseline = box.top + plotH;
    const max = days.reduce((acc, d) => Math.max(acc, d.taken, d.cancelled), 0);
    const scale = niceScale(max);
    const r1 = (n) => Math.round(n * 10) / 10;
    const xAt = (i) => (days.length <= 1 ? box.left + plotW / 2 : box.left + (plotW * i) / (days.length - 1));
    const yAt = (v) => baseline - (plotH * v) / scale.top;
    const pts = (key) => days.map((d, i) => [r1(xAt(i)), r1(yAt(d[key]))]);
    // About 5 evenly spread date labels (always includes first and last).
    const wanted = Math.min(days.length, 5);
    const xTicks = [];
    for (let k = 0; k < wanted; k++) {
      const i = wanted === 1 ? 0 : Math.round((k * (days.length - 1)) / (wanted - 1));
      if (!xTicks.some((t) => t.index === i)) xTicks.push({ index: i, x: r1(xAt(i)), label: fmtDayMonth(days[i].date) });
    }
    return {
      taken: pts("taken"),
      cancelled: pts("cancelled"),
      baseline,
      left: box.left,
      right: box.left + plotW,
      yTicks: scale.ticks.map((v) => ({ value: v, y: r1(yAt(v)) })),
      xTicks,
    };
  }

  function pointsAttr(points) {
    return points.map(([x, y]) => `${x},${y}`).join(" ");
  }

  // Closed polygon under a series (area fill).
  function areaPointsAttr(points, baseline) {
    if (!points.length) return "";
    const first = points[0];
    const last = points[points.length - 1];
    return `${pointsAttr(points)} ${last[0]},${baseline} ${first[0]},${baseline}`;
  }

  // Bar widths as % of the largest entry; a non-zero count never rounds to a
  // sliver that disappears.
  function barWidths(entries) {
    const list = Array.isArray(entries) ? entries : [];
    const max = list.reduce((acc, e) => Math.max(acc, e.count), 0);
    return list.map((e) => {
      if (!max || e.count <= 0) return 0;
      return Math.max(2, Math.round((e.count / max) * 100));
    });
  }

  // Heat cell: alpha of the accent color, and whether the number on top needs
  // dark text. Zero cells are empty (alpha 0). The count is always printed in
  // the cell, so intensity is never the only channel.
  function heatIntensity(count, max) {
    if (!count || count <= 0 || !max) return { alpha: 0, dark: false };
    const ratio = Math.min(1, count / max);
    const alpha = Math.round((0.18 + 0.62 * ratio) * 100) / 100;
    return { alpha, dark: ratio >= 0.6 };
  }

  // The API's weekday x hour matrix, defensively normalised to 7 rows x 24
  // integer columns (anything missing or malformed counts as 0).
  function heatMatrix(weekdayHour) {
    const rows = Array.isArray(weekdayHour) ? weekdayHour : [];
    return WEEKDAYS.map((_, d) =>
      Array.from({ length: 24 }, (_unused, h) => {
        const n = Number(Array.isArray(rows[d]) ? rows[d][h] : 0);
        return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
      })
    );
  }

  // Hours shown: 8..19 by default, widened to include any hour with data.
  function heatHourRange(weekdayHour) {
    let lo = HEAT_HOURS_MIN;
    let hi = HEAT_HOURS_MAX;
    heatMatrix(weekdayHour).forEach((row) =>
      row.forEach((count, h) => {
        if (count > 0) {
          lo = Math.min(lo, h);
          hi = Math.max(hi, h);
        }
      })
    );
    return { lo, hi };
  }

  // Monday-Saturday always; Sunday only when it has data.
  function heatWeekdayCount(weekdayHour) {
    return heatMatrix(weekdayHour)[6].some((count) => count > 0) ? 7 : 6;
  }

  // Everything the grid needs, as plain data: visible weekdays and hours, one
  // row of {count, alpha, dark} per weekday, intensity scaled to the largest
  // cell of the whole matrix.
  function heatGrid(weekdayHour) {
    const matrix = heatMatrix(weekdayHour);
    const { lo, hi } = heatHourRange(matrix);
    const dayCount = heatWeekdayCount(matrix);
    const max = matrix.reduce((acc, row) => Math.max(acc, ...row), 0);
    const hours = [];
    for (let h = lo; h <= hi; h++) hours.push(h);
    const rows = matrix.slice(0, dayCount).map((row, d) => ({
      label: WEEKDAYS[d],
      cells: hours.map((h) => ({ hour: h, count: row[h], ...heatIntensity(row[h], max) })),
    }));
    return { hours, rows, max };
  }

  function isEmptyKpis(data) {
    const t = data.totals;
    return t.taken.current === 0 && t.cancelled.current === 0 && t.rescheduled.current === 0;
  }

  function isIncomplete(data) {
    return Boolean(data.truncated || data.previous_truncated || (data.evidence && data.evidence.truncated));
  }

  // The with/without evidence split is complete unless the API says otherwise
  // (an older payload without the field counts as exact).
  function isEvidenceExact(data) {
    return !(data && data.evidence && data.evidence.exact === false);
  }

  const EVIDENCE_INEXACT_TEXT = "Evidencia incompleta: el período es demasiado largo para verificar todos los turnos";

  // A count that is only a lower bound when the evidence is not exact:
  // "3" or "al menos 3".
  function evidenceCountText(count, exact) {
    return exact ? fmtInt(count) : `al menos ${fmtInt(count)}`;
  }

  // Unmatched confirmations that could not be judged (evidence fetch truncated).
  function unverifiableCount(data) {
    const e = data && data.evidence ? data.evidence : {};
    return (e.taken_unverifiable || 0) + (e.cancelled_unverifiable || 0);
  }

  // What the screen shows after a load: stale means the numbers on screen belong
  // to an older period because the latest request failed.
  function staleView({ data, failed }) {
    if (!failed || !data || !data.period) return { stale: false, text: "" };
    return {
      stale: true,
      text: `Mostrando datos del período ${fmtDate(data.period.date_from)} al ${fmtDate(data.period.date_to)}; no se pudo cargar el nuevo período.`,
    };
  }

  // ------------------------------------------------------------ print/PDF
  // Pure helpers for the printed report (header, footer, file name, button
  // state). The DOM wiring is further down.

  // "KPIs-2026-09-16_2026-10-15": the browser proposes document.title as the
  // PDF file name, so ISO dates (sortable, no slashes) are used. Falls back to
  // plain "KPIs" when the period is missing or malformed.
  function printFileTitle(period) {
    if (!period || !isIsoDate(period.date_from) || !isIsoDate(period.date_to)) return "KPIs";
    return `KPIs-${period.date_from}_${period.date_to}`;
  }

  // "Período: 16 sep al 15 oct 2026" (the year is written on both ends only
  // when the period crosses a year).
  function printPeriodText(period) {
    if (!period || !isIsoDate(period.date_from) || !isIsoDate(period.date_to)) return "";
    const sameYear = period.date_from.slice(0, 4) === period.date_to.slice(0, 4);
    const from = sameYear ? fmtDayMonth(period.date_from) : fmtDateLong(period.date_from);
    return `Período: ${from} al ${fmtDateLong(period.date_to)}`;
  }

  // "15 oct 2026, 11:30" in the given IANA time zone (the clinic's). Hand
  // assembled from Intl parts so the result does not depend on the browser's
  // es-AR separators. Returns "" for an unparsable timestamp; an unknown zone
  // falls back to the browser's own.
  function formatClinicDateTime(iso, timeZone) {
    const date = new Date(iso);
    if (!iso || Number.isNaN(date.getTime())) return "";
    const options = { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
    let formatter;
    try {
      formatter = new Intl.DateTimeFormat("es-AR", { ...options, timeZone });
    } catch (e) {
      formatter = new Intl.DateTimeFormat("es-AR", options);
    }
    const part = Object.fromEntries(formatter.formatToParts(date).map((p) => [p.type, p.value]));
    return `${Number(part.day)} ${MONTHS[Number(part.month) - 1]} ${part.year}, ${part.hour}:${part.minute}`;
  }

  function printGeneratedText(iso, timeZone) {
    const text = formatClinicDateTime(iso, timeZone);
    return text ? `Generado: ${text}` : "";
  }

  // Footer caveat: how many taken bookings have no tool evidence.
  function printEvidenceText(data) {
    const total = data && data.totals ? data.totals.taken.current : 0;
    const without = data && data.evidence ? data.evidence.taken_without : 0;
    const rule = "Un turno cuenta como tomado cuando el paciente lo confirma";
    if (!total) return `${rule}.`;
    if (!isEvidenceExact(data)) {
      const lead = without ? `${rule}; al menos ${fmtInt(without)} de los ${fmtInt(total)} no tienen registro de la herramienta de Dentalink` : rule;
      return `${lead}. ${EVIDENCE_INEXACT_TEXT}.`;
    }
    if (!without) return `${rule}; todos los turnos tomados tienen registro de la herramienta de Dentalink.`;
    return `${rule}; ${fmtInt(without)} de los ${fmtInt(total)} ${without === 1 ? "no tiene" : "no tienen"} registro de la herramienta de Dentalink.`;
  }

  // Footer notice when the API analysed only part of the records; "" otherwise.
  function printTruncationText(data) {
    if (!data || !isIncomplete(data)) return "";
    return "Datos incompletos: el período tiene más registros de los que se pueden analizar, así que las cifras pueden ser menores a las reales o la comparación con el período anterior, inexacta.";
  }

  // Whether "Exportar PDF" may be used, and the reason shown when it may not.
  // Errored wins over data: after a failed refresh the screen keeps the old
  // numbers, but a report of possibly stale figures must not be printed.
  function exportAvailability({ loading, failed, hasData }) {
    if (loading) return { enabled: false, reason: "Esperá a que terminen de cargar los datos para exportar el PDF." };
    if (failed || !hasData) return { enabled: false, reason: "No hay datos cargados para exportar. Reintentá la carga primero." };
    return { enabled: true, reason: "" };
  }

  // ------------------------------------------------------------- rendering
  // Everything below needs a DOM (and ADMIN) and is not unit-tested in Node.

  const $ = (id) => document.getElementById(id);
  const esc = (v) => ADMIN.escapeHtml(v);
  const escAttr = (v) => esc(v).replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  function renderCards(data) {
    const t = data.totals;
    const taken = describeChange(t.taken);
    const cancelled = describeChange(t.cancelled);
    const without = data.evidence.taken_without;
    const exact = isEvidenceExact(data);
    const takenTotal = t.taken.current;
    // The printed report (KpisPrint.dc.html) uses shorter wording than the
    // screen: `print` is the short form, shown by the @media print rules only.
    const both = (screen, print) =>
      `<span class="kpi-screen-only">${esc(screen)}</span><span class="kpi-print-only">${esc(print)}</span>`;
    const card = (label, printLabel, value, sub, printSub, opts = {}) =>
      `<div class="kpi-card${opts.warn ? " kpi-card-warn" : ""}">
        <span class="kpi-card-label">${both(label, printLabel)}</span>
        <span class="kpi-card-value${opts.warn ? " kpi-warn-text" : ""}">${esc(typeof value === "string" ? value : fmtInt(value))}</span>
        <span class="kpi-card-sub${opts.dir ? " kpi-dir-" + opts.dir : ""}">${both(sub, printSub)}</span>
      </div>`;
    return (
      card("Turnos tomados por el bot", "Tomados por el bot", t.taken.current, taken.text, taken.print, { dir: taken.dir }) +
      card("Turnos cancelados (vía bot)", "Cancelados (vía bot)", t.cancelled.current, cancelled.text, cancelled.print) +
      card(
        "Turnos reprogramados (vía bot)",
        "Reprogramados (vía bot)",
        t.rescheduled.current,
        "Se cuentan aparte de los tomados",
        "Aparte de los tomados"
      ) +
      card(
        "Tomados sin evidencia registrada",
        "Sin evidencia registrada",
        evidenceCountText(without, exact),
        `de ${fmtInt(takenTotal)} tomados: sin registro de la herramienta de Dentalink`,
        `de los ${fmtInt(takenTotal)} tomados`,
        { warn: without > 0 }
      )
    );
  }

  function renderPerDayChart(data) {
    const g = seriesGeometry(data.per_day);
    const days = data.per_day;
    const label = `Turnos tomados y cancelados por día, del ${fmtDate(data.period.date_from)} al ${fmtDate(data.period.date_to)}. Tomados: ${fmtInt(data.totals.taken.current)}. Cancelados vía bot: ${fmtInt(data.totals.cancelled.current)}.`;
    const grid = g.yTicks
      .map((t) => `<line x1="${g.left}" y1="${t.y}" x2="${g.right}" y2="${t.y}"></line>`)
      .join("");
    const yLabels = g.yTicks
      .map((t) => `<text x="${g.left - 8}" y="${t.y + 4}" text-anchor="end">${fmtInt(t.value)}</text>`)
      .join("");
    const xLabels = g.xTicks
      .map((t) => `<text x="${t.x}" y="${g.baseline + 20}" text-anchor="middle">${esc(t.label)}</text>`)
      .join("");
    // With a single day a polyline draws nothing: show markers instead.
    const single = days.length === 1;
    const markers = single
      ? `<circle class="kpi-dot-taken" cx="${g.taken[0][0]}" cy="${g.taken[0][1]}" r="4"></circle>
         <rect class="kpi-dot-cancelled" x="${g.cancelled[0][0] - 4}" y="${g.cancelled[0][1] - 4}" width="8" height="8"></rect>`
      : "";
    const rows = days
      .map(
        (d) =>
          `<tr><td>${esc(fmtDate(d.date))}</td><td class="kpi-num">${esc(fmtInt(d.taken))}</td><td class="kpi-num">${esc(fmtInt(d.cancelled))}</td></tr>`
      )
      .join("");
    return `<section class="kpi-panel" aria-labelledby="kpi-h-perday">
      <div class="kpi-panel-head">
        <h2 id="kpi-h-perday">Turnos por día</h2>
        <div class="kpi-legend">
          <span><svg class="kpi-swatch" viewBox="0 0 28 8" aria-hidden="true"><line class="kpi-line-taken" x1="0" y1="4" x2="28" y2="4"></line></svg> Tomados</span>
          <span><svg class="kpi-swatch" viewBox="0 0 28 8" aria-hidden="true"><line class="kpi-line-cancelled" x1="0" y1="4" x2="28" y2="4"></line></svg> Cancelados (vía bot)</span>
        </div>
      </div>
      <svg class="kpi-svg" viewBox="0 0 ${CHART_BOX.width} ${CHART_BOX.height}" role="img" aria-label="${escAttr(label)}">
        <g class="kpi-grid">${grid}</g>
        <g class="kpi-axis kpi-axis-y">${yLabels}</g>
        <g class="kpi-axis">${xLabels}</g>
        <polygon class="kpi-area-taken" points="${areaPointsAttr(g.taken, g.baseline)}"></polygon>
        <polyline class="kpi-line-taken" points="${pointsAttr(g.taken)}"></polyline>
        <polyline class="kpi-line-cancelled" points="${pointsAttr(g.cancelled)}"></polyline>
        ${markers}
      </svg>
      <details class="kpi-details">
        <summary>Ver datos por día</summary>
        <div class="kpi-scroll"><table class="kpi-table">
          <thead><tr><th>Día</th><th class="kpi-num">Tomados</th><th class="kpi-num">Cancelados</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </details>
    </section>`;
  }

  function renderBars(id, title, entries, barClass, emptyText) {
    const widths = barWidths(entries);
    const rows = entries
      .map(
        (e, i) => `<li class="kpi-bar-row">
          <span class="kpi-bar-label" title="${escAttr(e.label)}">${esc(e.label)}</span>
          <span class="kpi-bar-track" aria-hidden="true"><span class="kpi-bar-fill ${barClass}" style="width:${widths[i]}%"></span></span>
          <span class="kpi-bar-count">${esc(fmtInt(e.count))}</span>
        </li>`
      )
      .join("");
    return `<section class="kpi-panel" aria-labelledby="${id}">
      <h2 id="${id}">${esc(title)}</h2>
      ${entries.length ? `<ul class="kpi-bars">${rows}</ul>` : `<p class="kpi-muted">${esc(emptyText)}</p>`}
    </section>`;
  }

  // A real <table>: row/column headers give screen readers the weekday and hour
  // of every cell. Empty cells carry a visually hidden "0".
  function renderHeat(data) {
    const grid = heatGrid(data.weekday_hour);
    const head = grid.hours.map((h) => `<th scope="col">${esc(h)}</th>`).join("");
    const body = grid.rows
      .map((row) => {
        const cells = row.cells
          .map((c) => {
            // Alpha goes through a custom property so the print stylesheet can
            // swap the (screen) accent color for the printable one.
            const style = c.alpha ? ` style="--a:${c.alpha}"` : "";
            const cls = `kpi-heat-cell${c.dark ? " kpi-heat-dark" : ""}${c.count ? "" : " kpi-heat-zero"}`;
            const title = `${row.label} ${c.hour}:00 — ${fmtInt(c.count)}`;
            const content = c.count ? esc(fmtInt(c.count)) : '<span class="kpi-sr">0</span>';
            return `<td class="${cls}"${style} title="${escAttr(title)}">${content}</td>`;
          })
          .join("");
        return `<tr><th scope="row">${esc(row.label)}</th>${cells}</tr>`;
      })
      .join("");
    const note =
      data.without_slot > 0
        ? `<p class="kpi-muted">${esc(fmtInt(data.without_slot))} ${data.without_slot === 1 ? "turno tomado no tiene" : "turnos tomados no tienen"} fecha y hora de turno válidas y no aparece${data.without_slot === 1 ? "" : "n"} en este gráfico.</p>`
        : "";
    return `<section class="kpi-panel" aria-labelledby="kpi-h-heat">
      <div class="kpi-panel-head">
        <h2 id="kpi-h-heat">Día y hora de los turnos tomados</h2>
        <span class="kpi-muted"><span class="kpi-screen-only">Hora de la clínica (Buenos Aires). Cada celda indica la cantidad de turnos; más oscuro, más turnos.</span><span class="kpi-print-only">Hora de la clínica. Cada celda: cantidad de turnos.</span></span>
      </div>
      <div class="kpi-scroll" role="region" aria-labelledby="kpi-h-heat" tabindex="0">
        <table class="kpi-heat">
          <caption class="kpi-sr">Turnos tomados por día de la semana (filas) y hora (columnas)</caption>
          <thead><tr><td class="kpi-heat-corner"></td>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
      ${note}
    </section>`;
  }

  function renderEvidence(data) {
    const e = data.evidence;
    const exact = isEvidenceExact(data);
    const row = (label, count, criteria, warn, lowerBound) =>
      `<tr><td>${esc(label)}</td><td class="kpi-num${warn && count > 0 ? " kpi-warn-text" : ""}">${esc(evidenceCountText(count, !lowerBound))}</td><td class="kpi-muted">${esc(criteria)}</td></tr>`;
    return `<section class="kpi-panel kpi-screen-only" aria-labelledby="kpi-h-evidence">
      <h2 id="kpi-h-evidence">Cómo se contó</h2>
      <div class="kpi-scroll"><table class="kpi-table">
        <thead><tr><th>Concepto</th><th class="kpi-num">Cantidad</th><th>Criterio</th></tr></thead>
        <tbody>
          ${row("Tomados con evidencia", e.taken_with, "Confirmación del paciente y herramienta de Dentalink completada")}
          ${row("Tomados sin evidencia", e.taken_without, "Confirmados por el paciente, sin registro de la herramienta", true, !exact)}
          ${row("Cancelados vía bot con evidencia", e.cancelled_with, "Confirmación del paciente y herramienta de Dentalink completada")}
          ${row("Cancelados vía bot sin evidencia", e.cancelled_without, "No incluye cancelaciones hechas por el equipo en Dentalink", true, !exact)}
          ${unverifiableCount(data) > 0 ? row("Sin poder verificar", unverifiableCount(data), "Confirmaciones más antiguas que el último registro de herramienta analizado", false, false) : ""}
        </tbody>
      </table></div>
      ${exact ? "" : `<p class="kpi-muted">${esc(EVIDENCE_INEXACT_TEXT)}.</p>`}
    </section>`;
  }

  function renderContent(data) {
    if (isEmptyKpis(data)) {
      return `<div class="kpi-empty" role="status">
        <strong>Sin turnos en el período</strong>
        <span class="kpi-muted">No hay turnos tomados, cancelados ni reprogramados por el bot entre el ${esc(fmtDate(data.period.date_from))} y el ${esc(fmtDate(data.period.date_to))}.</span>
      </div>`;
    }
    return (
      renderPerDayChart(data) +
      `<div class="kpi-two">` +
      renderBars("kpi-h-pro", "Profesionales más pedidos", data.top_professionals, "kpi-fill-accent", "Sin datos de profesionales.") +
      renderBars("kpi-h-spe", "Especialidades más pedidas", data.top_specialties, "kpi-fill-ok", "Sin datos de especialidades.") +
      `</div>` +
      renderHeat(data) +
      renderEvidence(data)
    );
  }

  // ----------------------------------------------------------------- state

  const S = {
    range: null, // {from, to} currently shown/requested
    today: null, // clinic "today" once known, browser date until then
    todayFromApi: false,
    custom: false, // custom editor open
    data: null,
    seq: 0,
    controller: null,
    loading: true, // first request in flight
    failed: false, // last request failed
    savedTitle: null, // document.title while printing, restored afterwards
  };

  // Print-only header/footer text and the export button state. Everything goes
  // in through textContent, so nothing from the API can inject markup.
  function fillPrint(data) {
    const zone = $("kpi-print-head").dataset.timezone;
    $("kpi-print-period").textContent = printPeriodText(data.period);
    $("kpi-print-generated").textContent = printGeneratedText(data.generated_at, zone);
    $("kpi-print-evidence").textContent = printEvidenceText(data);
    const trunc = printTruncationText(data);
    $("kpi-print-trunc").textContent = trunc;
    $("kpi-print-trunc").hidden = !trunc;
    $("kpi-main").classList.add("kpi-printable");
  }

  function syncExport() {
    const state = exportAvailability({ loading: S.loading, failed: S.failed, hasData: Boolean(S.data) });
    const btn = $("kpi-export");
    btn.setAttribute("aria-disabled", String(!state.enabled));
    btn.title = state.reason;
    $("kpi-export-hint").textContent = state.reason;
  }

  function onExport() {
    if ($("kpi-export").getAttribute("aria-disabled") === "true") return;
    window.print();
  }

  // The saved PDF is named after document.title: swap it while printing.
  function onBeforePrint() {
    if (!S.data || S.savedTitle !== null) return;
    S.savedTitle = document.title;
    document.title = printFileTitle(S.data.period);
  }

  function onAfterPrint() {
    if (S.savedTitle === null) return;
    document.title = S.savedTitle;
    S.savedTitle = null;
  }

  function setHash(range) {
    const hash = serializeHash(range);
    if (!hash) return;
    try {
      history.replaceState(null, "", `${location.pathname}${location.search}${hash}`);
    } catch (e) {
      /* replaceState can throw in sandboxed frames; the URL is a convenience */
    }
  }

  function showBanner(message) {
    const banner = $("kpi-banner");
    banner.hidden = !message;
    if (message) $("kpi-banner-text").textContent = message;
  }

  function syncControls() {
    const preset = S.custom ? "custom" : detectPreset(S.range, S.today);
    document.querySelectorAll("#kpi-presets button").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.preset === preset));
    });
    $("kpi-custom").hidden = !S.custom;
    $("kpi-from").max = S.today;
    $("kpi-to").max = S.today;
  }

  // Old numbers kept after a failed load: say which period they belong to and
  // mute them. Cleared by the next successful load.
  function syncStale() {
    const view = staleView({ data: S.data, failed: S.failed });
    const notice = $("kpi-stale");
    notice.hidden = !view.stale;
    $("kpi-stale-text").textContent = view.text;
    $("kpi-cards").classList.toggle("kpi-stale-data", view.stale);
    $("kpi-content").classList.toggle("kpi-stale-data", view.stale);
  }

  function syncPeriodText(data) {
    const el = $("kpi-period-text");
    if (!data) {
      el.textContent = S.range ? `${fmtDateLong(S.range.from)} al ${fmtDateLong(S.range.to)}` : "";
      el.removeAttribute("title");
      return;
    }
    el.textContent = `${fmtDateLong(data.period.date_from)} al ${fmtDateLong(data.period.date_to)} · Comparado con el período anterior`;
    // The earlier period's own dates, for whoever wants them.
    el.title = `Período anterior: ${fmtDateLong(data.previous_period.date_from)} al ${fmtDateLong(data.previous_period.date_to)}`;
  }

  // `range` null means "no explicit period": ask the API for its default (the
  // last 30 days up to the clinic's today) and adopt the period it echoes.
  async function load(range) {
    const seq = ++S.seq;
    if (S.controller) S.controller.abort();
    S.controller = new AbortController();
    const main = $("kpi-main");
    main.setAttribute("aria-busy", "true");
    main.classList.add("kpi-busy");
    $("kpi-refresh").disabled = true;
    S.loading = true;
    syncExport();
    const query = range ? `?from=${range.from}&to=${range.to}` : "";
    try {
      const response = await ADMIN.apiFetch(`/kpis${query}`, { signal: S.controller.signal });
      if (seq !== S.seq) return;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (seq !== S.seq) return;
      S.data = data;
      S.failed = false;
      S.range = { from: data.period.date_from, to: data.period.date_to };
      if (!range) {
        S.today = data.period.date_to;
        S.todayFromApi = true;
      }
      showBanner("");
      syncStale();
      fillPrint(data);
      $("kpi-incomplete").hidden = !isIncomplete(data);
      $("kpi-evidence-inexact").hidden = isEvidenceExact(data);
      $("kpi-cards").innerHTML = renderCards(data);
      $("kpi-content").innerHTML = renderContent(data);
      $("kpi-updated").textContent = `Actualizado ${ADMIN.formatDateTime(data.generated_at)}`;
      syncPeriodText(data);
      setHash(S.range);
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (seq !== S.seq) return;
      S.failed = true;
      // Stay usable: keep whatever was on screen, explain, offer a retry.
      showBanner("No se pudieron cargar los KPIs. Revisá la conexión e intentá de nuevo.");
      syncStale();
      if (S.data) syncPeriodText(S.data);
      if (!S.data) {
        $("kpi-cards").innerHTML = "";
        $("kpi-content").innerHTML = "";
      }
    } finally {
      if (seq === S.seq) {
        main.setAttribute("aria-busy", "false");
        main.classList.remove("kpi-busy");
        $("kpi-refresh").disabled = false;
        S.loading = false;
        syncExport();
        syncControls();
      }
    }
  }

  function applyRange(range) {
    S.range = range;
    S.custom = false;
    syncControls();
    syncPeriodText(null);
    return load(range);
  }

  function onPreset(value) {
    if (value === "custom") {
      S.custom = true;
      if (S.range) {
        $("kpi-from").value = S.range.from;
        $("kpi-to").value = S.range.to;
      }
      $("kpi-custom-error").textContent = "";
      syncControls();
      $("kpi-from").focus();
      return;
    }
    applyRange(presetRange(Number(value), S.today));
  }

  function onApply() {
    const from = $("kpi-from").value;
    const to = $("kpi-to").value;
    const problem = validateRange(from, to);
    $("kpi-custom-error").textContent = problem || "";
    if (problem) return;
    applyRange({ from, to });
  }

  function init() {
    return ADMIN.requireAuth().then((me) => {
      $("who-label").textContent = `${me.username} · ${me.role}`;
      $("logout-btn").addEventListener("click", ADMIN.logout);

      document.querySelectorAll("#kpi-presets button").forEach((btn) => {
        btn.addEventListener("click", () => onPreset(btn.dataset.preset));
      });
      $("kpi-apply").addEventListener("click", onApply);
      $("kpi-custom").addEventListener("keydown", (event) => {
        if (event.key === "Enter") onApply();
      });
      $("kpi-refresh").addEventListener("click", () => load(S.range));
      $("kpi-retry").addEventListener("click", () => load(S.range));
      // The A4 report comes from the @media print rules in style.css.
      $("kpi-export").addEventListener("click", onExport);
      window.addEventListener("beforeprint", onBeforePrint);
      window.addEventListener("afterprint", onAfterPrint);
      window.addEventListener("hashchange", () => {
        const next = parseHash(location.hash);
        if (next && (!S.range || next.from !== S.range.from || next.to !== S.range.to)) applyRange(next);
      });

      S.today = browserToday();
      const initial = parseHash(location.hash);
      if (initial) {
        S.range = initial;
        syncControls();
        syncPeriodText(null);
        return load(initial);
      }
      syncControls();
      return load(null);
    });
  }

  return {
    init,
    isIsoDate,
    addDays,
    daysInRange,
    browserToday,
    validateRange,
    presetRange,
    detectPreset,
    parseHash,
    serializeHash,
    fmtInt,
    fmtPct,
    fmtDate,
    fmtDateLong,
    fmtDayMonth,
    describeChange,
    niceScale,
    seriesGeometry,
    pointsAttr,
    areaPointsAttr,
    barWidths,
    heatIntensity,
    heatMatrix,
    heatHourRange,
    heatWeekdayCount,
    heatGrid,
    isEmptyKpis,
    isIncomplete,
    isEvidenceExact,
    evidenceCountText,
    unverifiableCount,
    staleView,
    EVIDENCE_INEXACT_TEXT,
    printFileTitle,
    printPeriodText,
    formatClinicDateTime,
    printGeneratedText,
    printEvidenceText,
    printTruncationText,
    exportAvailability,
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = Kpis;
}
if (typeof document !== "undefined" && document.getElementById("kpi-main")) {
  Kpis.init();
}
