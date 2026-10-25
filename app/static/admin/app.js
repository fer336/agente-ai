// Shared helpers for the admin panel's static pages (PRD.md §44). No
// build step, no framework — plain fetch() against the JSON API at
// /admin/api/*, cookie-based session (set by POST /admin/login).

const ADMIN = (() => {
  const API_BASE = "/admin/api";

  function readCookie(name) {
    const match = document.cookie.match(
      new RegExp("(?:^|; )" + name.replace(/([.$?*|{}()[\]\\/+^])/g, "\\$1") + "=([^;]*)")
    );
    return match ? decodeURIComponent(match[1]) : null;
  }

  // Wraps fetch() with the panel's session cookie (sent automatically by
  // the browser) and, for mutating methods, the CSRF header the backend's
  // double-submit check requires (app/api/dependencies/auth.py's
  // require_csrf). A 401 here always means "no valid session" (PRD.md
  // §74.3's generic auth-failure message) — the caller never had a good
  // reason to be on an admin page in the first place, so this redirects
  // to the login page immediately rather than making every page repeat
  // that check.
  async function apiFetch(path, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const headers = Object.assign({}, options.headers || {});
    if (method !== "GET") {
      const csrf = readCookie("admin_csrf");
      if (csrf) headers["X-CSRF-Token"] = csrf;
    }
    const response = await fetch(API_BASE + path, {
      ...options,
      method,
      headers,
      credentials: "include",
    });
    if (response.status === 401) {
      window.location.href = "/admin/login";
      throw new Error("Not authenticated");
    }
    return response;
  }

  // Confirms the session is valid and returns {username, role} — every
  // page calls this on load, both as its auth check and to know whether
  // to show ADMIN_TECHNICAL-only controls (resolve error, reset
  // conversation). Hiding those for other roles is cosmetic only: the
  // backend enforces the real restriction on every mutating route
  // regardless of what the UI shows (PRD.md §74.3).
  async function requireAuth() {
    const response = await apiFetch("/me");
    if (!response.ok) {
      window.location.href = "/admin/login";
      throw new Error("Not authenticated");
    }
    return response.json();
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value === null || value === undefined ? "" : String(value);
    return div.innerHTML;
  }

  // Control label of a conversation: "agent" = the bot answers, anything else = staff took
  // over (Chatwoot's "administracion"). The text always accompanies the color.
  function modeBadge(mode) {
    const isAgent = mode === "agent";
    return `<span class="badge mode-${isAgent ? "agent" : "human"}">${isAgent ? "Agente" : "Administración"}</span>`;
  }

  function formatDateTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return escapeHtml(iso);
    return date.toLocaleString("es-AR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function qs(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  async function logout() {
    // /admin/logout lives outside /admin/api (it's an auth action, not a
    // data-layer route) — called directly rather than through apiFetch,
    // which always prefixes API_BASE. No CSRF header: the route itself
    // requires none (app/api/routes/admin_auth.py).
    await fetch("/admin/logout", { method: "POST", credentials: "include" });
    window.location.href = "/admin/login";
  }

  // Shows a strip at the very top of the page while the agent is paused. Purely
  // informational and defensive: it uses a plain fetch (not apiFetch, so a 401
  // never redirects), skips pages without a top bar (login) and the control page
  // itself, and swallows every error.
  //
  // The fetch is asynchronous, so a banner that only appears after it would push
  // the page down on every load. The last known state is therefore kept in
  // sessionStorage and the strip is drawn at once from it; the fetch then
  // confirms or removes it (the page only moves when the state actually changed).
  const PAUSED_KEY = "admin_agent_paused";

  function rememberPaused(paused) {
    try {
      sessionStorage.setItem(PAUSED_KEY, paused ? "1" : "0");
    } catch (error) {
      // Storage can be unavailable (private window, blocked site data).
    }
  }

  function mountPausedBanner() {
    if (document.querySelector(".pause-banner")) return;
    const banner = document.createElement("div");
    banner.className = "pause-banner";
    banner.setAttribute("role", "status");
    banner.innerHTML =
      "<strong>El agente está pausado.</strong> <span>No envía mensajes automáticos.</span> " +
      '<a href="/admin/agent-control">Ir al control del agente</a>';
    document.body.insertAdjacentElement("afterbegin", banner);
  }

  async function showPausedBanner() {
    try {
      if (!document.querySelector(".topbar") || window.location.pathname === "/admin/agent-control") return;
      let hinted = false;
      try {
        hinted = sessionStorage.getItem(PAUSED_KEY) === "1";
      } catch (error) {
        hinted = false;
      }
      if (hinted) mountPausedBanner();
      const response = await fetch(API_BASE + "/agent-control", { credentials: "include" });
      if (!response.ok) return;
      const state = await response.json();
      const paused = Boolean(state) && state.agent_paused === true;
      rememberPaused(paused);
      if (paused) mountPausedBanner();
      else document.querySelectorAll(".pause-banner").forEach((node) => node.remove());
    } catch (error) {
      // Never break a page because the banner could not be shown.
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", showPausedBanner);
  } else {
    showPausedBanner();
  }

  return { apiFetch, requireAuth, escapeHtml, formatDateTime, modeBadge, qs, logout, rememberPaused };
})();
