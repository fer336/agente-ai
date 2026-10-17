// Agent control page: global pause switch and per-contact filter.
// Backend: GET/PUT /admin/api/agent-control (ADMIN_TECHNICAL / ADMIN_CLINIC
// may change it; READ_ONLY only reads — the backend enforces it, the
// disabled controls here are cosmetic).

(async () => {
  const me = await ADMIN.requireAuth();
  document.getElementById("who-label").textContent = `${me.username} · ${me.role}`;
  document.getElementById("logout-btn").addEventListener("click", ADMIN.logout);

  const canEdit = me.role === "ADMIN_TECHNICAL" || me.role === "ADMIN_CLINIC";
  const el = (id) => document.getElementById(id);
  const statusBox = el("ctl-status");
  const toggle = el("ctl-toggle");
  const form = el("ctl-filter-form");
  let state = null;

  if (!canEdit) el("ctl-readonly-note").hidden = false;

  function feedback(id, kind, text) {
    const node = el(id);
    node.textContent = text;
    node.className = "ctl-feedback" + (kind ? ` is-${kind}` : "");
  }

  function render() {
    const paused = state.agent_paused;
    statusBox.classList.toggle("is-paused", paused);
    statusBox.classList.toggle("is-active", !paused);
    el("ctl-status-title").textContent = paused ? "Agente PAUSADO" : "Agente activo";
    el("ctl-status-detail").textContent = paused
      ? `Pausado por ${state.paused_by || "—"} el ${ADMIN.formatDateTime(state.paused_at)}. No envía respuestas, seguimientos ni recordatorios.`
      : "Responde a los pacientes con normalidad.";
    toggle.textContent = paused ? "Reanudar agente" : "Pausar agente";
    toggle.disabled = !canEdit;

    el("ctl-mode").value = state.contact_filter_mode;
    el("ctl-phones").value = state.contact_filter_phones.join("\n");
    el("ctl-mode").disabled = !canEdit;
    el("ctl-phones").disabled = !canEdit;
    el("ctl-save").disabled = !canEdit;
  }

  async function errorText(response, fallback) {
    const payload = await response.json().catch(() => null);
    return (payload && typeof payload.detail === "string" && payload.detail) || fallback;
  }

  async function save(body, feedbackId, okText) {
    feedback(feedbackId, "", "Guardando…");
    try {
      const response = await ADMIN.apiFetch("/agent-control", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        feedback(feedbackId, "error", await errorText(response, "No se pudo guardar el cambio."));
        return;
      }
      state = await response.json();
      render();
      feedback(feedbackId, "ok", okText);
    } catch (error) {
      feedback(feedbackId, "error", "No se pudo guardar el cambio.");
    }
  }

  function parsePhones(text) {
    return text.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean);
  }

  toggle.addEventListener("click", () => {
    if (!state || !canEdit) return;
    const pausing = !state.agent_paused;
    const question = pausing
      ? "¿Pausar el agente?\n\nMientras esté pausado NO se enviará ningún mensaje: ni respuestas, ni seguimientos, ni recordatorios. Los mensajes de los pacientes se siguen guardando."
      : "¿Reanudar el agente?\n\nVolverá a responder a los próximos mensajes. No se envía nada de lo que quedó pendiente durante la pausa.";
    if (!window.confirm(question)) return;
    save(
      {
        agent_paused: pausing,
        contact_filter_mode: state.contact_filter_mode,
        contact_filter_phones: state.contact_filter_phones,
      },
      "ctl-toggle-feedback",
      pausing ? "Agente pausado." : "Agente reanudado."
    );
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state || !canEdit) return;
    save(
      {
        agent_paused: state.agent_paused,
        contact_filter_mode: el("ctl-mode").value,
        contact_filter_phones: parsePhones(el("ctl-phones").value),
      },
      "ctl-filter-feedback",
      "Filtro guardado."
    );
  });

  try {
    const response = await ADMIN.apiFetch("/agent-control");
    if (!response.ok) throw new Error("load failed");
    state = await response.json();
    render();
  } catch (error) {
    el("ctl-status-title").textContent = "No se pudo cargar el estado del agente.";
  }
})();
