// Shared LangGraph flowchart renderer for the admin panel's conversation
// and run detail pages (PRD.md §44.2 used to show a flat "✓/✗ node_name"
// text list instead — this replaces it with the actual agent graph,
// colored by what ran/failed in one turn). No build step, plain JS,
// loaded after Mermaid's own CDN <script> tag and after app.js.
//
// The flowchart below is a hand-authored mirror of app/agent/graph.py's
// real topology (node names match NodeExecutionResponse.node_name
// verbatim) — there is no runtime export of the graph from the backend,
// so this must be kept in sync by hand if graph.py's topology changes.
const AdminGraph = (() => {
  const BASE_DEFINITION = `flowchart TD
    START(("Inicio")) --> check_conversation_mode
    check_conversation_mode -- error --> handle_error
    check_conversation_mode -- "modo humano (silencioso)" --> FIN(("Fin"))
    check_conversation_mode -- reactivación --> fresh_restart
    check_conversation_mode -- normal --> resolve_interaction
    fresh_restart --> FIN
    resolve_interaction -- error --> handle_error
    resolve_interaction -- cierre --> FIN
    resolve_interaction -- appointment --> appointment
    resolve_interaction -- insurance --> agreement
    resolve_interaction -- specialties --> specialties
    resolve_interaction -- handoff --> handoff
    resolve_interaction -- question --> question
    resolve_interaction -- location --> location
    resolve_interaction -- "(default)" --> fallback
    appointment -- error --> handle_error
    appointment --> FIN
    agreement -- error --> handle_error
    agreement --> FIN
    specialties -- error --> handle_error
    specialties --> FIN
    handoff -- error --> handle_error
    handoff --> FIN
    question -- error --> handle_error
    question --> FIN
    location -- error --> handle_error
    location --> FIN
    fallback -- error --> handle_error
    fallback --> FIN
    handle_error --> FIN
    classDef notReached fill:#20242c,stroke:#2a2e38,color:#9aa0ac;
    classDef completed fill:#3ecf8e,stroke:#2a2e38,color:#0f1115;
    classDef failed fill:#f0576a,stroke:#2a2e38,color:#0f1115;`;

  //: Nodes the flowchart actually tracks per turn — must match
  //: app/agent/graph.py's node-name constants exactly (every business
  //: node `with_error_handling` wraps, PRD.md §29/§40).
  const TRACKED_NODES = [
    "check_conversation_mode",
    "resolve_interaction",
    "fresh_restart",
    "appointment",
    "agreement",
    "specialties",
    "handoff",
    "question",
    "location",
    "fallback",
    "handle_error",
  ];

  let _initialized = false;
  let _instanceCounter = 0;

  function _ensureInit() {
    if (_initialized) return;
    mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });
    _initialized = true;
  }

  function _classify(nodeExecutions) {
    const byNode = {};
    nodeExecutions.forEach((node) => {
      byNode[node.node_name] = node;
    });
    const classes = {};
    TRACKED_NODES.forEach((name) => {
      const execution = byNode[name];
      classes[name] = !execution ? "notReached" : execution.status === "failed" ? "failed" : "completed";
    });
    return { classes, byNode };
  }

  //: Renders one flowchart into `containerEl`, colored by `nodeExecutions`,
  //: and wires node clicks to `onDetailChange(executionOrNull)`.
  //:
  //: `instanceId` MUST be stable across repeated calls for the same
  //: on-screen graph (e.g. the agent_run id) — it names a per-instance
  //: global click-handler function (`window[...]`) that this render call
  //: registers/overwrites. A page showing several graphs at once
  //: (conversation-detail.html, one per agent_run) needs this: Mermaid's
  //: `click nodeId call fn()` binding only resolves a PLAIN global
  //: function name, so without a per-instance name every graph's clicks
  //: would resolve to the same shared handler and clobber each other's
  //: `onDetailChange`/node data — reusing the same stable name across a
  //: polling refresh avoids leaking a fresh `window` property every tick.
  async function render(containerEl, nodeExecutions, onDetailChange, instanceId) {
    _ensureInit();
    const { classes, byNode } = _classify(nodeExecutions || []);

    const fnName = "__adminGraphClick_" + String(instanceId).replace(/[^a-zA-Z0-9_]/g, "_");
    window[fnName] = (nodeName) => {
      if (onDetailChange) onDetailChange(byNode[nodeName] || null);
    };

    const clickLines = TRACKED_NODES.map((name) => `click ${name} call ${fnName}()`).join("\n");
    const classLines = Object.entries(classes)
      .map(([name, cls]) => `class ${name} ${cls};`)
      .join("\n");

    _instanceCounter += 1;
    const { svg, bindFunctions } = await mermaid.render(
      "admin-graph-svg-" + _instanceCounter,
      BASE_DEFINITION + "\n" + clickLines + "\n" + classLines
    );
    containerEl.innerHTML = svg;
    if (bindFunctions) bindFunctions(containerEl);
  }

  //: Renders the "click a node" detail panel's inner HTML for one
  //: NodeExecutionResponse (or a "nothing selected" placeholder when
  //: `execution` is null) — shared so both pages format it identically.
  function renderDetail(execution) {
    if (!execution) {
      return '<p class="muted">Seleccioná un nodo ejecutado para ver el detalle.</p>';
    }
    const ok = execution.status !== "failed";
    return `
      <dl class="field-grid">
        <div><dt>Nodo</dt><dd><span class="mark ${ok ? "ok" : "fail"}">${ok ? "✓" : "✗"}</span> ${ADMIN.escapeHtml(execution.node_name)}</dd></div>
        <div><dt>Estado</dt><dd>${ADMIN.escapeHtml(execution.status)}</dd></div>
        <div><dt>Duración</dt><dd>${execution.duration_ms}ms</dd></div>
        <div><dt>Entrada</dt><dd>${ADMIN.escapeHtml(execution.input_summary || "—")}</dd></div>
        <div><dt>Salida</dt><dd>${ADMIN.escapeHtml(execution.output_summary || "—")}</dd></div>
        <div><dt>Error</dt><dd>${
          execution.error_id
            ? `<a class="link" href="/admin/errors/${encodeURIComponent(execution.error_id)}">ver error</a>`
            : '<span class="muted">—</span>'
        }</dd></div>
      </dl>
    `;
  }

  //: Refreshes every ~intervalMs while the tab is visible — the backend
  //: only ever commits a turn's whole trace at once, at the end
  //: (open_sqlalchemy_trace_repositories), so there is never anything new
  //: to see faster than that; pausing on a hidden tab avoids polling a
  //: page nobody is looking at. Returns a stop() function.
  function startPolling(reloadFn, intervalMs = 10000) {
    function tick() {
      if (document.visibilityState === "visible") reloadFn();
    }
    const timer = setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }

  return { render, renderDetail, startPolling };
})();
