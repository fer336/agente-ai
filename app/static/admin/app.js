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

  return { apiFetch, requireAuth, escapeHtml, formatDateTime, qs, logout };
})();
