// Agent diagram page (/admin/agent). Plain browser JS, no build step.
//
// The topology comes from GET /admin/api/graphs and is laid out ONCE per graph
// (cached); the live numbers come from GET /admin/api/graphs/state and are only
// patched into the existing SVG (classes + text), so nodes never move between
// polls. Auto-cycle, keyboard shortcuts, URL hash state and reduced-motion
// handling live in the "interaction" section; their decisions are pure
// functions (parseHash, serializeHash, nextIndex, cycleState, nodeAriaLabel)
// exported for Node so they can be exercised without a browser.
//
// Run mode (`#run=<agent_run_id>`) swaps the live aggregates for one agent
// run: the nodes are colored from GET /admin/api/runs/{id}, the cycle and the
// polling stay off, and a banner offers the way back to the live state.
// summarizeRun, pickRunGraph, describeRunNode and runNodeAriaLabel are the pure
// parts of it.

const AgentDiagram = (() => {
  "use strict";

  // ---------------------------------------------------------------- layout --

  // Measures of the approved canvas (Main.dc.html): 176x64 boxes, an 87x36
  // "Inicio" pill, a 191x64 error box, a 44px "Fin" bar.
  const GRID = 4;
  const NODE_W = 176;
  const NODE_H = 64;
  const START_W = 87;
  const START_H = 36;
  const GEN_START_W = 88; // even, so the pill's centre sits on the 4 px grid like the boxes
  const DUMMY_W = 8; // virtual node that reserves a column for a long edge
  const GAP_X = 24;
  const MARGIN = 16;
  const MIN_CHANNEL = 48;
  const LANE_STEP = 8;
  const ERR_W = 191;
  const ERR_H = 64;
  const FIN_H = 44;
  const ERROR_NODE_ID = "handle_error";

  // Fixed composition of the main graph on the canvas (see canvasPlan).
  const CV = {
    margin: 17,
    tallW: 112,
    tallH: 96,
    tallGap: 6,
    topY: 24, // top row: side node and error box
    midY: 136, // entry and router
    busY: 236, // horizontal bus under the router
    leafY: 272,
    finY: 456,
    height: 520,
    minWidth: 880,
    colGap: 48, // start -> entry
    routerGap: 96, // entry -> router
  };
  // Canvas order of the leaf row: nodes that feed each other sit side by side.
  // Ids not listed keep the topology order, after the listed ones.
  const LEAF_ORDER = [
    "reminder_action",
    "appointment",
    "handoff",
    "specialties",
    "agreement",
    "question",
    "faq_topic",
    "payment_admin",
    "location",
    "fallback",
  ];

  const snap = (v) => Math.round(v / GRID) * GRID;
  const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;

  // Drops edges that close a cycle (found by DFS) so ranking is well defined.
  // The agent graphs are DAGs today; this only guards against a future loop,
  // whose back edge would simply not be drawn.
  function removeBackEdges(nodes, edges) {
    const out = new Map(nodes.map((n) => [n.id, []]));
    edges.forEach((e, i) => out.get(e.from).push(i));
    const color = new Map();
    const back = new Set();
    const visit = (id) => {
      color.set(id, 1);
      for (const i of out.get(id)) {
        const c = color.get(edges[i].to) || 0;
        if (c === 1) back.add(i);
        else if (c === 0) visit(edges[i].to);
      }
      color.set(id, 2);
    };
    [...nodes.filter((n) => n.kind === "start"), ...nodes].forEach((n) => {
      if (!color.get(n.id)) visit(n.id);
    });
    return edges.filter((_, i) => !back.has(i));
  }

  // Longest-path ranking: rank(v) = 1 + max rank of its predecessors.
  function assignRanks(nodes, edges) {
    const preds = new Map(nodes.map((n) => [n.id, []]));
    edges.forEach((e) => preds.get(e.to).push(e.from));
    const rank = new Map();
    const rk = (id) => {
      if (rank.has(id)) return rank.get(id);
      const ps = preds.get(id);
      const r = ps.length ? Math.max(...ps.map(rk)) + 1 : 0;
      rank.set(id, r);
      return r;
    };
    nodes.forEach((n) => rk(n.id));
    return rank;
  }

  /**
   * Pure layered layout (Sugiyama style, no DOM).
   *
   * Edges to `__end__` and to `handle_error` are NOT laid out: nearly every
   * node has both, and drawing them would bury the diagram in lines. They are
   * summarised instead by one "Fin" band under the last rank and one
   * handle_error box (with a caption) in the top-right corner.
   *
   * Steps: longest-path ranking -> dummy nodes for edges spanning several
   * ranks -> barycenter ordering (keeping the best crossing count) -> x by
   * parent/child averages with minimum spacing -> orthogonal routing with one
   * horizontal "bus" lane per source (lanes stack when their spans overlap).
   * All coordinates are on a 4 px grid. Ranks run top to bottom.
   */
  function computeLayout(graph) {
    const plan = canvasPlan(graph);
    if (plan) return computeCanvasLayout(graph, plan);
    const endIds = new Set(graph.nodes.filter((n) => n.kind === "end").map((n) => n.id));
    const errorNode = graph.nodes.find((n) => n.id === ERROR_NODE_ID) || null;
    const layoutNodes = graph.nodes.filter((n) => !endIds.has(n.id) && n.id !== ERROR_NODE_ID);
    const known = new Set(layoutNodes.map((n) => n.id));
    const rawEdges = graph.edges.filter((e) => known.has(e.from) && known.has(e.to) && e.from !== e.to);
    const edges = removeBackEdges(layoutNodes, rawEdges);
    const rank = assignRanks(layoutNodes, edges);

    // Items = real nodes + dummies. links = consecutive chain pairs.
    const items = new Map();
    layoutNodes.forEach((n) => {
      const isStart = n.kind === "start";
      items.set(n.id, {
        id: n.id,
        node: n,
        rank: rank.get(n.id),
        w: isStart ? GEN_START_W : NODE_W,
        h: isStart ? START_H : NODE_H,
      });
    });
    const chains = edges.map((e, idx) => {
      const chain = [e.from];
      for (let r = rank.get(e.from) + 1; r < rank.get(e.to); r++) {
        const id = `~${idx}:${r}`;
        items.set(id, { id, node: null, rank: r, w: DUMMY_W, h: NODE_H });
        chain.push(id);
      }
      chain.push(e.to);
      return chain;
    });
    const links = [];
    const up = new Map([...items.keys()].map((k) => [k, []]));
    const down = new Map([...items.keys()].map((k) => [k, []]));
    chains.forEach((chain, idx) => {
      for (let i = 0; i + 1 < chain.length; i++) {
        links.push({ a: chain[i], b: chain[i + 1], idx });
        down.get(chain[i]).push(chain[i + 1]);
        up.get(chain[i + 1]).push(chain[i]);
      }
    });

    const maxRank = Math.max(0, ...[...items.values()].map((it) => it.rank));
    const layers = Array.from({ length: maxRank + 1 }, () => []);
    [...items.values()].forEach((it) => layers[it.rank].push(it.id));

    // --- ordering: barycenter sweeps, keep the ordering with fewest crossings.
    const pos = new Map();
    const reindex = (row) => row.forEach((id, i) => pos.set(id, i));
    layers.forEach(reindex);
    const crossings = () => {
      let total = 0;
      for (let r = 0; r < maxRank; r++) {
        const ls = links.filter((l) => items.get(l.a).rank === r);
        for (let i = 0; i < ls.length; i++) {
          for (let j = i + 1; j < ls.length; j++) {
            const da = pos.get(ls[i].a) - pos.get(ls[j].a);
            const db = pos.get(ls[i].b) - pos.get(ls[j].b);
            if (da * db < 0) total++;
          }
        }
      }
      return total;
    };
    let best = layers.map((l) => l.slice());
    let bestScore = crossings();
    for (let it = 0; it < 8 && bestScore > 0; it++) {
      const downward = it % 2 === 0;
      const order = [];
      for (let r = downward ? 1 : maxRank - 1; downward ? r <= maxRank : r >= 0; r += downward ? 1 : -1) {
        order.push(r);
      }
      order.forEach((r) => {
        const adj = downward ? up : down;
        const keyed = layers[r].map((id, i) => {
          const ns = adj.get(id);
          return { id, i, key: ns.length ? mean(ns.map((n) => pos.get(n))) : i };
        });
        keyed.sort((p, q) => p.key - q.key || p.i - q.i);
        layers[r] = keyed.map((k) => k.id);
        reindex(layers[r]);
      });
      const score = crossings();
      if (score < bestScore) {
        bestScore = score;
        best = layers.map((l) => l.slice());
      }
    }
    best.forEach((row, r) => {
      layers[r] = row;
      reindex(row);
    });

    // --- x coordinates (centres): centred rows, then pulled towards neighbours.
    const cx = new Map();
    const rowWidth = (row) => row.reduce((s, id) => s + items.get(id).w, 0) + GAP_X * (row.length - 1);
    const widest = Math.max(0, ...layers.map(rowWidth));
    layers.forEach((row) => {
      let x = (widest - rowWidth(row)) / 2;
      row.forEach((id) => {
        cx.set(id, x + items.get(id).w / 2);
        x += items.get(id).w + GAP_X;
      });
    });
    const settle = (row, adj) => {
      const want = row.map((id) => {
        const ns = adj.get(id);
        return ns.length ? mean(ns.map((n) => cx.get(n))) : cx.get(id);
      });
      const placed = [];
      let edge = 0;
      row.forEach((id, i) => {
        const half = items.get(id).w / 2;
        const c = i === 0 ? want[i] : Math.max(want[i], edge + GAP_X + half);
        placed.push(c);
        edge = c + half;
      });
      const shift = mean(want.map((w, i) => w - placed[i]));
      row.forEach((id, i) => cx.set(id, placed[i] + shift));
    };
    for (let r = 1; r <= maxRank; r++) settle(layers[r], up);
    for (let r = maxRank - 1; r >= 0; r--) settle(layers[r], down);
    for (let r = 1; r <= maxRank; r++) settle(layers[r], up);
    const minLeft = Math.min(...[...items.values()].map((it) => cx.get(it.id) - it.w / 2));
    items.forEach((it) => cx.set(it.id, snap(cx.get(it.id) - it.w / 2 - minLeft + MARGIN) + it.w / 2));
    const contentRight = Math.max(...[...items.values()].map((it) => cx.get(it.id) + it.w / 2));
    const hasError = errorNode !== null;
    const width = snap(Math.max(contentRight + MARGIN, hasError ? 2 * MARGIN + ERR_W + 240 : 2 * MARGIN + 320));

    // --- ports: incoming edges spread along the target's top side.
    const inPort = new Map(); // `${idx}:${targetId}` -> x
    items.forEach((it) => {
      const incoming = links.filter((l) => l.b === it.id).sort((p, q) => cx.get(p.a) - cx.get(q.a) || p.idx - q.idx);
      const k = incoming.length;
      const step = k > 1 ? Math.max(GRID, Math.min(16, Math.floor((it.w - 32) / (k - 1) / GRID) * GRID)) : 0;
      incoming.forEach((l, i) => {
        const offset = it.node ? snap(i * step - ((k - 1) * step) / 2) : 0;
        inPort.set(`${l.idx}:${it.id}`, cx.get(it.id) + offset);
      });
    });

    // --- lanes: per channel (gap between rank r and r+1), one bus per source item.
    const laneIndex = new Map(); // `${r}:${a}` -> lane number
    const channelHeight = [];
    for (let r = 0; r < maxRank; r++) {
      const groups = new Map();
      links
        .filter((l) => items.get(l.a).rank === r)
        .forEach((l) => {
          const xs = [cx.get(l.a), inPort.get(`${l.idx}:${l.b}`)];
          const g = groups.get(l.a) || { a: l.a, lo: Infinity, hi: -Infinity };
          g.lo = Math.min(g.lo, ...xs);
          g.hi = Math.max(g.hi, ...xs);
          groups.set(l.a, g);
        });
      const moving = [...groups.values()].filter((g) => g.hi > g.lo).sort((p, q) => p.lo - q.lo);
      const laneEnds = [];
      moving.forEach((g) => {
        let lane = laneEnds.findIndex((end) => g.lo - end >= LANE_STEP);
        if (lane === -1) lane = laneEnds.length;
        laneEnds[lane] = g.hi;
        laneIndex.set(`${r}:${g.a}`, lane);
      });
      channelHeight.push(Math.max(MIN_CHANNEL, 32 + Math.max(laneEnds.length - 1, 0) * LANE_STEP));
    }

    // --- y coordinates.
    const topPad = hasError ? 128 : 64;
    const rowTop = [];
    const channelTop = [];
    let y = topPad;
    for (let r = 0; r <= maxRank; r++) {
      rowTop.push(y);
      channelTop.push(y + NODE_H);
      y += NODE_H + (r < maxRank ? channelHeight[r] : 0);
    }
    const lastBottom = y;
    const laneY = (r, a) => channelTop[r] + 16 + (laneIndex.get(`${r}:${a}`) || 0) * LANE_STEP;

    // --- polylines.
    const nodes = layoutNodes.map((n) => {
      const it = items.get(n.id);
      return {
        id: n.id,
        label: n.label,
        kind: n.kind,
        traced: n.traced,
        variant: n.kind === "start" ? "start" : "wide",
        x: cx.get(n.id) - it.w / 2,
        y: rowTop[it.rank] + (NODE_H - it.h) / 2,
        w: it.w,
        h: it.h,
      };
    });
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const outEdges = chains.map((chain, idx) => {
      const first = nodeById.get(chain[0]);
      const lastId = chain[chain.length - 1];
      const pts = [[cx.get(chain[0]), first.y + first.h]];
      for (let i = 0; i + 1 < chain.length; i++) {
        const a = chain[i];
        const b = chain[i + 1];
        const ly = laneY(items.get(a).rank, a);
        pts.push([cx.get(a), ly], [inPort.get(`${idx}:${b}`), ly]);
      }
      pts.push([inPort.get(`${idx}:${lastId}`), nodeById.get(lastId).y]);
      return { from: edges[idx].from, to: edges[idx].to, conditional: edges[idx].conditional, points: simplify(pts) };
    });

    const fin = endIds.size
      ? { x: MARGIN, y: snap(lastBottom + 48), w: width - 2 * MARGIN, h: FIN_H }
      : null;
    const height = snap((fin ? fin.y + fin.h : lastBottom) + MARGIN);
    const errorBox = hasError
      ? { id: errorNode.id, label: errorNode.label, x: width - MARGIN - ERR_W, y: 24, w: ERR_W, h: ERR_H }
      : null;
    return { width, height, nodes, edges: outEdges, fin, errorBox, title: { x: MARGIN, y: 30 } };
  }

  /**
   * Recognises the shape of the main graph and returns its parts, or null.
   *
   * start -> entry; the entry fans out to one router and at most one "side"
   * node that only ends; the router fans out to every other node (the leaves).
   * Anything else (several entries, a deeper tree, unreachable nodes) falls back
   * to the generic layered layout, so a changed topology still renders.
   */
  function canvasPlan(graph) {
    const start = graph.nodes.find((n) => n.kind === "start");
    if (!start) return null;
    const core = graph.nodes.filter((n) => n.kind !== "end" && n.id !== ERROR_NODE_ID);
    const known = new Set(core.map((n) => n.id));
    const out = (id) => [...new Set(graph.edges.filter((e) => e.from === id && known.has(e.to) && e.to !== id).map((e) => e.to))];
    const entries = out(start.id);
    if (entries.length !== 1) return null;
    const entry = entries[0];
    const next = out(entry)
      .map((id) => ({ id, out: out(id) }))
      .sort((a, b) => b.out.length - a.out.length);
    if (!next.length || next[0].out.length < 2 || next.length > 2) return null;
    const router = next[0].id;
    const side = next.length === 2 ? next[1].id : null;
    if (side && next[1].out.length) return null;
    const seen = new Set([router]);
    const queue = [router];
    while (queue.length) out(queue.shift()).forEach((id) => {
      if (!seen.has(id)) {
        seen.add(id);
        queue.push(id);
      }
    });
    seen.delete(router);
    const fixed = [start.id, entry, router, ...(side ? [side] : [])];
    if (fixed.some((id) => seen.has(id)) || fixed.length + seen.size !== core.length) return null;
    const order = (id) => {
      const i = LEAF_ORDER.indexOf(id);
      return i === -1 ? LEAF_ORDER.length + core.findIndex((n) => n.id === id) : i;
    };
    const leaves = [...seen].sort((a, b) => order(a) - order(b));
    return { start: start.id, entry, router, side, leaves };
  }

  // Fixed-coordinate layout of the canvas composition (1208x520 for ten leaves):
  // the entry and the router on the middle band, the side node above the entry,
  // one bus from the router down to a single row of tall leaf boxes, the "Fin"
  // bar below and the error box at the top right.
  function computeCanvasLayout(graph, plan) {
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const m = CV.margin;
    const place = (id, x, y, w, h, variant) => {
      const n = byId.get(id);
      return { id, label: n.label, kind: n.kind, traced: n.traced, variant, x, y, w, h };
    };
    const count = plan.leaves.length;
    const leavesW = count * CV.tallW + (count - 1) * CV.tallGap;
    const width = Math.max(CV.minWidth, 2 * m + leavesW);
    const start = place(plan.start, m, CV.midY + (NODE_H - START_H) / 2, START_W, START_H, "start");
    const entry = place(plan.entry, start.x + START_W + CV.colGap, CV.midY, NODE_W, NODE_H, "wide");
    const router = place(plan.router, entry.x + NODE_W + CV.routerGap, CV.midY, NODE_W, NODE_H, "wide");
    const nodes = [start, entry, router];
    let side = null;
    if (plan.side) {
      side = place(plan.side, entry.x, CV.topY, NODE_W, NODE_H, "wide");
      nodes.push(side);
    }
    const leaves = plan.leaves.map((id, i) =>
      place(id, m + i * (CV.tallW + CV.tallGap), CV.leafY, CV.tallW, CV.tallH, "tall")
    );
    nodes.push(...leaves);
    const midLine = CV.midY + NODE_H / 2;
    const cx = (n) => n.x + n.w / 2;
    const edges = [
      { from: start.id, to: entry.id, points: [[start.x + start.w, midLine], [entry.x, midLine]] },
      { from: entry.id, to: router.id, points: [[entry.x + NODE_W, midLine], [router.x, midLine]] },
    ];
    if (side) edges.push({ from: entry.id, to: side.id, points: [[cx(entry), entry.y], [cx(entry), side.y + side.h]] });
    leaves.forEach((leaf) => {
      edges.push({
        from: router.id,
        to: leaf.id,
        points: simplify([
          [cx(router), router.y + router.h],
          [cx(router), CV.busY],
          [cx(leaf), CV.busY],
          [cx(leaf), leaf.y],
        ]),
      });
    });
    const errorNode = graph.nodes.find((n) => n.id === ERROR_NODE_ID) || null;
    const hasEnd = graph.nodes.some((n) => n.kind === "end");
    return {
      width,
      height: CV.height,
      nodes,
      edges,
      fin: hasEnd ? { x: m, y: CV.finY, w: width - 2 * m, h: FIN_H } : null,
      errorBox: errorNode
        ? { id: errorNode.id, label: errorNode.label, x: width - m - ERR_W, y: CV.topY, w: ERR_W, h: ERR_H }
        : null,
      title: { x: m, y: 30 },
    };
  }

  // Removes repeated points and the middle point of collinear triples.
  function simplify(pts) {
    const out = [];
    pts.forEach((p) => {
      const last = out[out.length - 1];
      if (last && last[0] === p[0] && last[1] === p[1]) return;
      out.push(p);
    });
    for (let i = out.length - 2; i > 0; i--) {
      const [a, b, c] = [out[i - 1], out[i], out[i + 1]];
      if ((a[0] === b[0] && b[0] === c[0]) || (a[1] === b[1] && b[1] === c[1])) out.splice(i, 1);
    }
    return out;
  }

  // Splits `text` right after any character of `breakChars`. Equivalent to
  // text.split(/(?<=[chars])/) without a lookbehind, which Safari before 16.4 rejects at
  // parse time (that would break the whole page).
  function splitAfter(text, breakChars) {
    const out = [];
    let cur = "";
    for (const ch of text) {
      cur += ch;
      if (breakChars.includes(ch)) {
        out.push(cur);
        cur = "";
      }
    }
    if (cur) out.push(cur);
    return out;
  }

  // Splits a snake_case name into at most two lines of <= maxChars.
  function splitName(label, maxChars = 20) {
    const parts = splitAfter(label, "_");
    const lines = [""];
    parts.forEach((p) => {
      const cur = lines[lines.length - 1];
      if (cur && (cur + p).length > maxChars && lines.length < 2) lines.push(p);
      else lines[lines.length - 1] = cur + p;
    });
    return lines.map((l) => (l.length > maxChars + 2 ? l.slice(0, maxChars + 1) + "…" : l));
  }

  // Text width in px for the SVG labels. Uses an offscreen canvas with the same
  // font as the page (an SVG that is display:none cannot be measured); without
  // a canvas (Node, old engines) it falls back to a flat 7 px per character.
  let measureCtx = null;
  function textWidth(text, bold) {
    try {
      if (measureCtx === null) measureCtx = document.createElement("canvas").getContext("2d") || false;
      if (measureCtx) {
        const family = getComputedStyle(document.body).fontFamily || "sans-serif";
        measureCtx.font = `${bold ? 600 : 400} 12px ${family}`;
        return measureCtx.measureText(text).width;
      }
    } catch (e) {
      measureCtx = false;
    }
    return text.length * 7;
  }

  // Greedy wrap of `text` into lines of at most `maxPx`, breaking after "_" (for
  // ids) or at spaces (for prose). A single piece wider than maxPx stays whole.
  function wrapText(text, maxPx, bold, breakChars = "_ ") {
    const lines = [];
    splitAfter(text, breakChars).forEach((piece) => {
      const cur = lines[lines.length - 1];
      if (cur !== undefined && textWidth((cur + piece).trimEnd(), bold) <= maxPx) lines[lines.length - 1] = cur + piece;
      else lines.push(piece);
    });
    return lines.map((l) => l.trimEnd());
  }

  // ------------------------------------------------------------ formatting --

  let intFormat;
  try {
    intFormat = new Intl.NumberFormat("es-AR", { useGrouping: "always" });
  } catch (e) {
    intFormat = new Intl.NumberFormat("es-AR");
  }
  const oneDecimal = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  const fmtInt = (n) => intFormat.format(n);

  function fmtMs(ms) {
    if (ms === null || ms === undefined) return "—";
    if (ms < 1000) return `${fmtInt(Math.round(ms))} ms`;
    if (ms < 60000) return `${oneDecimal.format(ms / 1000)} s`;
    return `${oneDecimal.format(ms / 60000)} min`;
  }

  function fmtAgo(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    if (s < 60) return `hace ${s} s`;
    if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
    return `hace ${Math.floor(s / 3600)} h`;
  }

  const plural = (n, one, many) => `${fmtInt(n)} ${n === 1 ? one : many}`;

  // ----------------------------------------------------------- interaction --
  // Pure helpers (no DOM, no timers).

  const WINDOW_IDS = ["15m", "1h", "24h"];
  const DEFAULT_WINDOW = "1h";
  const CYCLE_MS = 8000;
  const ID_PATTERN = /^[A-Za-z0-9_.:-]{1,64}$/;

  // Parses `#g=<graph>&focus=<node>&w=<window>&play=<0|1>&run=<agent_run_id>`.
  // Returns only the keys that hold a well-formed value; anything unknown or
  // malformed is left undefined so the caller falls back to its default. Ids
  // are only shape-checked here: whether the graph/node/run exists is the
  // caller's call. The values are never used as HTML. A `run` that is present
  // but malformed is reported as `runInvalid` so the page can say so instead of
  // silently showing the live state.
  function parseHash(hash) {
    const out = { g: undefined, focus: undefined, w: undefined, play: undefined, run: undefined, runInvalid: false };
    const text = String(hash || "").replace(/^#/, "");
    let params;
    try {
      params = new URLSearchParams(text);
    } catch (e) {
      return out;
    }
    const g = params.get("g");
    if (g !== null && ID_PATTERN.test(g)) out.g = g;
    const focus = params.get("focus");
    if (focus !== null && ID_PATTERN.test(focus)) out.focus = focus;
    const w = params.get("w");
    if (w !== null && WINDOW_IDS.includes(w)) out.w = w;
    const run = params.get("run");
    if (run !== null) {
      if (ID_PATTERN.test(run)) out.run = run;
      else out.runInvalid = true;
    }
    const play = params.get("play");
    if (play === "0") out.play = false;
    else if (play === "1") out.play = true;
    return out;
  }

  // Inverse of parseHash. Omits keys without a value; `focus` only when set.
  function serializeHash(state) {
    const parts = [];
    if (state.g) parts.push(`g=${encodeURIComponent(state.g)}`);
    if (state.focus) parts.push(`focus=${encodeURIComponent(state.focus)}`);
    if (state.w) parts.push(`w=${encodeURIComponent(state.w)}`);
    if (typeof state.play === "boolean") parts.push(`play=${state.play ? 1 : 0}`);
    if (state.run) parts.push(`run=${encodeURIComponent(state.run)}`);
    return parts.length ? `#${parts.join("&")}` : "";
  }

  // Wrapping index step (Prev = -1, Next = +1).
  function nextIndex(index, delta, count) {
    if (!(count > 0)) return 0;
    return (((index + delta) % count) + count) % count;
  }

  // Decides whether the auto-cycle should be ticking. `play` is the user's
  // intent (manual pause, node pin, reduced-motion default); the rest are
  // transient conditions that pause without changing the intent.
  // Returns "running" or the reason it is not: "run" (run mode never cycles),
  // "idle" (fewer than 2 graphs), "paused" (intent off), "hidden", "hover", "focus".
  function cycleState({ play, hovering, focusInside, hidden, graphCount, runMode }) {
    if (runMode) return "run";
    if (!(graphCount > 1)) return "idle";
    if (!play) return "paused";
    if (hidden) return "hidden";
    if (hovering) return "hover";
    if (focusInside) return "focus";
    return "running";
  }

  // Accessible name of a node: its name plus its state, e.g.
  // "appointment, 54 ejecuciones, 2 fallos".
  function nodeAriaLabel(name, traced, ns, loading) {
    if (!traced) return `${name}, interno, sin datos de nodo`;
    if (loading) return `${name}, cargando`;
    if (!ns || ns.count === 0) return `${name}, sin ejecuciones`;
    const runs = plural(ns.count, "ejecución", "ejecuciones");
    let state;
    if (ns.failed > 0) state = plural(ns.failed, "fallo", "fallos");
    else state = ns.running > 0 ? "sin fallos, en curso" : "sin fallos";
    return `${name}, ${runs}, ${state}`;
  }

  // ---------------------------------------------------------------- run mode --

  const RUN_TEXT = { ok: "OK", fail: "Fallo", running: "En curso", none: "No ejecutado" };

  // Folds GET /admin/api/runs/{id} into per-node states keyed by node name. A
  // node can execute more than once in a run, so: fail if any execution failed,
  // else running if any is still running, else ok. Duration is the sum of the
  // finished executions (null while running). Tool executions are attached to
  // their node through node_execution_id.
  function summarizeRun(detail) {
    const run = (detail && detail.agent_run) || {};
    const execs = Array.isArray(detail && detail.node_executions) ? detail.node_executions : [];
    const tools = Array.isArray(detail && detail.tool_executions) ? detail.tool_executions : [];
    const nodes = {};
    execs
      .slice()
      .sort((a, b) => String(a.started_at).localeCompare(String(b.started_at)))
      .forEach((e) => {
        const n = nodes[e.node_name] || (nodes[e.node_name] = { status: "ok", count: 0, durationMs: 0, errorId: null, executionIds: [], tools: [] });
        n.count += 1;
        n.executionIds.push(e.id);
        if (e.status === "failed") {
          n.status = "fail";
          if (!n.errorId && e.error_id) n.errorId = e.error_id;
        } else if (e.status === "running" && n.status !== "fail") {
          n.status = "running";
        }
        if (!n.errorId && e.error_id) n.errorId = e.error_id;
        n.durationMs += Number(e.duration_ms) || 0;
      });
    Object.values(nodes).forEach((n) => {
      if (n.status === "running") n.durationMs = null;
      n.tools = tools.filter((t) => n.executionIds.includes(t.node_execution_id));
    });
    return {
      id: run.id,
      status: run.status,
      startedAt: run.started_at,
      errorId: run.error_id || null,
      hasFailure: Object.values(nodes).some((n) => n.status === "fail") || run.status === "failed",
      nodes,
    };
  }

  // Graph whose traced nodes best match the nodes the run executed. `preferred`
  // (an explicit g= in the URL) wins when it exists; ties and runs that matched
  // nothing fall back to the first graph (main).
  function pickRunGraph(graphs, nodeNames, preferredId) {
    if (!graphs.length) return -1;
    const pref = graphs.findIndex((g) => g.id === preferredId);
    if (pref >= 0) return pref;
    const names = new Set(nodeNames);
    let best = 0;
    let bestScore = -1;
    graphs.forEach((g, i) => {
      const score = g.nodes.filter((n) => n.traced && names.has(n.id)).length;
      if (score > bestScore) {
        best = i;
        bestScore = score;
      }
    });
    return best;
  }

  // What a traced node shows in run mode. `rs` is a summarizeRun node entry or
  // undefined (not executed in this run).
  function describeRunNode(rs) {
    if (!rs) return { cls: "idle", metric: "—", dot: "○", text: RUN_TEXT.none };
    const metric = fmtMs(rs.durationMs) + (rs.count > 1 ? ` · ${fmtInt(rs.count)}×` : "");
    if (rs.status === "fail") return { cls: "fail", metric, dot: "●", text: RUN_TEXT.fail };
    if (rs.status === "running") return { cls: "run", metric, dot: "◐", text: RUN_TEXT.running };
    return { cls: "ok", metric, dot: "●", text: RUN_TEXT.ok };
  }

  function runNodeAriaLabel(name, traced, rs, loading) {
    if (!traced) return `${name}, interno, sin datos de nodo`;
    if (loading) return `${name}, cargando`;
    if (!rs) return `${name}, no ejecutado en esta corrida`;
    const status = { ok: "OK", fail: "fallo", running: "en curso" }[rs.status];
    return `${name}, ${status}, ${fmtMs(rs.durationMs)}`;
  }

  // ------------------------------------------------------------- rendering --

  const SVG_NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, String(v)));
    if (parent) parent.appendChild(e);
    return e;
  }

  function svgText(parent, cls, x, y, text) {
    const t = svgEl("text", { class: cls, x, y, "text-anchor": "middle" }, parent);
    if (text !== undefined) t.textContent = text;
    return t;
  }

  // Builds the SVG for one graph. Returns the element plus handles to the
  // pieces that polling patches.
  function buildSvg(graph, layout) {
    const svg = svgEl("svg", {
      class: "agd-svg",
      width: layout.width,
      height: layout.height,
      viewBox: `0 0 ${layout.width} ${layout.height}`,
      role: "group",
      "aria-label": `Diagrama del grafo ${graph.label}`,
    });
    const markerId = `agd-arrow-${graph.id}`;
    const defs = svgEl("defs", {}, svg);
    const marker = svgEl(
      "marker",
      { id: markerId, markerWidth: 8, markerHeight: 8, refX: 7, refY: 4, orient: "auto", markerUnits: "userSpaceOnUse" },
      defs
    );
    svgEl("path", { class: "agd-arrow-head", d: "M0 0 L8 4 L0 8 Z" }, marker);

    svgText(svg, "agd-title", layout.title.x, layout.title.y, `Grafo ${graph.label.toLowerCase()}`).setAttribute(
      "text-anchor",
      "start"
    );

    const edgeLayer = svgEl("g", { class: "agd-edges" }, svg);
    layout.edges.forEach((e) => {
      const d = e.points.map((p, i) => `${i ? "L" : "M"} ${p[0]} ${p[1]}`).join(" ");
      svgEl("path", { class: "agd-edge", d, "marker-end": `url(#${markerId})` }, edgeLayer);
    });

    if (layout.fin) {
      const g = svgEl("g", { class: "agd-fin" }, svg);
      svgEl("rect", { x: layout.fin.x, y: layout.fin.y, width: layout.fin.w, height: layout.fin.h, rx: 8 }, g);
      svgText(g, "agd-fin-text", layout.fin.x + layout.fin.w / 2, layout.fin.y + layout.fin.h / 2 + 4, "Fin: todos los nodos terminan aquí");
    }

    const views = new Map();
    layout.nodes.forEach((n) => {
      if (n.kind === "start") {
        const g = svgEl("g", { class: "agd-start", transform: `translate(${n.x} ${n.y})` }, svg);
        svgEl("rect", { width: n.w, height: n.h, rx: n.h / 2 }, g);
        svgText(g, "agd-start-text", n.w / 2, n.h / 2 + 4, "Inicio");
        return;
      }
      views.set(n.id, buildNode(svg, n));
    });

    let caption = null;
    if (layout.errorBox) {
      const b = layout.errorBox;
      const g = svgEl(
        "g",
        {
          class: "agd-node agd-error",
          transform: `translate(${b.x} ${b.y})`,
          "data-node-id": b.id,
          tabindex: 0,
          role: "button",
        },
        svg
      );
      svgEl("rect", { width: b.w, height: b.h, rx: 8 }, g);
      const note = wrapText("Recibe el error de cualquier nodo", b.w - 16, false);
      let ey = (b.h - (note.length + 1) * 16) / 2 + 12;
      svgText(g, "agd-name", b.w / 2, ey, b.label);
      note.forEach((line) => {
        ey += 16;
        svgText(g, "agd-metric", b.w / 2, ey, line);
      });
      caption = svgText(svg, "agd-caption", b.x + b.w / 2, b.y + b.h + 20, "—");
      views.set(b.id, { g, caption, isError: true, traced: false, label: b.label });
    }
    return { svg, views, caption };
  }

  function buildNode(parent, n) {
    const g = svgEl(
      "g",
      {
        class: "agd-node agd-s-loading",
        transform: `translate(${n.x} ${n.y})`,
        "data-node-id": n.id,
        tabindex: 0,
        role: "button",
      },
      parent
    );
    svgEl("rect", { width: n.w, height: n.h, rx: 8 }, g);
    // Wide boxes show "metric · ● state" on one line (as on the canvas); the
    // tall leaf boxes and the untraced ones use one line for each.
    const oneLine = n.variant !== "tall" && n.traced;
    const nameLines = wrapText(n.label, n.w - (n.variant === "tall" ? 12 : 16), true, "_");
    const total = nameLines.length + (oneLine ? 1 : 2);
    let y = (n.h - total * 16) / 2 + 12;
    const cx = n.w / 2;
    nameLines.forEach((line) => {
      svgText(g, "agd-name", cx, y, line);
      y += 16;
    });
    let metric = null;
    let sep = null;
    let state;
    if (oneLine) {
      state = svgEl("text", { class: "agd-state", x: cx, y, "text-anchor": "middle" }, g);
      metric = svgEl("tspan", { class: "agd-metric" }, state);
      sep = svgEl("tspan", { class: "agd-metric" }, state);
      metric.textContent = "…";
      sep.textContent = " · ";
    } else {
      if (n.traced) {
        metric = svgText(g, "agd-metric", cx, y, "…");
      } else {
        svgText(g, "agd-badge", cx, y, "interno, sin trazado");
      }
      y += 16;
      state = svgEl("text", { class: "agd-state", x: cx, y, "text-anchor": "middle" }, g);
    }
    const dot = svgEl("tspan", { class: "agd-dot" }, state);
    const label = svgEl("tspan", { class: "agd-state-text", dx: 4 }, state);
    dot.textContent = "○";
    label.textContent = n.traced ? "Cargando" : "Sin datos de nodo";
    if (!n.traced) g.setAttribute("class", "agd-node agd-s-nodata");
    return { g, metric, sep, dot, label, traced: n.traced, name: n.label };
  }

  // Derives what a node should show from its state entry (or lack of one).
  function describeNode(view, ns, loading) {
    if (!view.traced) return { cls: "nodata", metric: null, dot: "○", text: "Sin datos de nodo" };
    if (loading) return { cls: "loading", metric: "…", dot: "○", text: "Cargando" };
    if (!ns || ns.count === 0) return { cls: "idle", metric: "Sin ejecuciones", dot: "○", text: "Sin datos" };
    const metric = `${fmtInt(ns.count)} · ${fmtMs(ns.avg_ms)}`;
    if (ns.failed > 0) return { cls: "fail", metric, dot: "●", text: plural(ns.failed, "fallo", "fallos") };
    return { cls: "ok", metric, dot: "●", text: ns.running > 0 ? "En curso" : "OK" };
  }

  function patchNode(view, ns, loading) {
    paintNode(view, describeNode(view, ns, loading), nodeAriaLabel(view.name, view.traced, ns, loading));
  }

  function patchRunNode(view, rs, loading) {
    const d = !view.traced
      ? describeNode(view, undefined, false)
      : loading
        ? describeNode(view, undefined, true)
        : describeRunNode(rs);
    paintNode(view, d, runNodeAriaLabel(view.name, view.traced, rs, loading));
  }

  function paintNode(view, d, aria) {
    const keepSelected = view.g.classList.contains("agd-selected") ? " agd-selected" : "";
    view.g.setAttribute("class", `agd-node agd-s-${d.cls}${keepSelected}`);
    if (view.metric && view.metric.textContent !== d.metric) view.metric.textContent = d.metric;
    if (view.sep) view.sep.textContent = d.metric ? " · " : "";
    if (view.dot.textContent !== d.dot) view.dot.textContent = d.dot;
    if (view.label.textContent !== d.text) view.label.textContent = d.text;
    view.g.setAttribute("aria-label", aria);
  }

  // ------------------------------------------------------------ controller --

  const WINDOW_PHRASE = { "15m": "últimos 15 min", "1h": "última hora", "24h": "últimas 24 h" };
  const POLL_MS = 5000;
  const BACKOFF_MS = 30000;

  const S = {
    graphs: [],
    built: new Map(), // graph id -> {layout, svg, views}
    active: 0,
    win: "1h",
    selected: {}, // graph id -> node id
    data: null, // last good /graphs/state payload
    fetchedAt: 0,
    generatedMs: 0,
    stale: false,
    timer: null,
    generation: 0,
    controller: null,
    detailHtml: null,
    // Interaction state. `play` is the user's intent; hovering/focusInside/
    // document.hidden pause the cycle without changing it.
    play: true,
    hovering: false,
    focusInside: false,
    reduced: false,
    cycleTimer: null,
    cycleMs: CYCLE_MS,
    // Run mode: null when live, else {id, state: "loading"|"ready"|"error",
    // summary, message}. While set, nothing polls and nothing cycles.
    run: null,
    runSeq: 0,
    runController: null,
    ready: false, // topology loaded and hash applied: only then is the hash written
    applying: false, // true while applying a hash: suppresses intermediate writes
  };

  const $ = (id) => document.getElementById(id);

  function showBanner(message, withRetry) {
    const b = $("agd-banner");
    b.hidden = !message;
    b.textContent = "";
    if (!message) return;
    const span = document.createElement("span");
    span.textContent = message;
    b.appendChild(span);
    if (withRetry) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Reintentar";
      btn.addEventListener("click", withRetry);
      b.appendChild(btn);
    }
  }

  function activeGraph() {
    return S.graphs[S.active];
  }

  function renderTabs() {
    const tabs = $("agd-tabs");
    tabs.textContent = "";
    S.graphs.forEach((g, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "tab");
      btn.id = `agd-tab-${g.id}`;
      btn.setAttribute("aria-controls", "agd-stage");
      btn.textContent = g.label;
      btn.addEventListener("click", () => setActive(i));
      tabs.appendChild(btn);
    });
    syncTabs();
  }

  function syncTabs() {
    S.graphs.forEach((g, i) => {
      const btn = $(`agd-tab-${g.id}`);
      btn.setAttribute("aria-selected", String(i === S.active));
      btn.tabIndex = i === S.active ? 0 : -1;
    });
    const stage = $("agd-stage");
    stage.setAttribute("aria-labelledby", `agd-tab-${activeGraph().id}`);
  }

  function ensureBuilt(graph) {
    if (!S.built.has(graph.id)) {
      const layout = computeLayout(graph);
      const { svg, views, caption } = buildSvg(graph, layout);
      svg.setAttribute("hidden", ""); // SVGElement has no .hidden property
      $("agd-canvas").appendChild(svg);
      S.built.set(graph.id, { layout, svg, views, caption });
      patchGraph(graph.id);
    }
    return S.built.get(graph.id);
  }

  // The stage keeps its natural size and scrolls inside its panel. Only when it
  // is just a little wider than the panel (down to 92%, text still >= 11 px) it
  // is scaled to fit, to avoid a scrollbar for a few pixels; below that, shrinking
  // would make the 12 px labels unreadable, so the panel scrolls instead.
  const FIT_MIN_SCALE = 0.92;

  function fitStage() {
    const b = S.built.get(activeGraph().id);
    if (!b) return;
    const avail = Math.floor($("agd-canvas").clientWidth);
    const { width, height } = b.layout;
    const scale = avail > 0 && avail < width && avail / width >= FIT_MIN_SCALE ? avail / width : 1;
    b.svg.style.width = scale === 1 ? "" : `${avail}px`;
    b.svg.style.height = scale === 1 ? "" : `${Math.round(height * scale)}px`;
  }

  function setActive(index) {
    const n = S.graphs.length;
    S.active = ((index % n) + n) % n;
    S.graphs.forEach((g) => {
      const b = ensureBuilt(g);
      if (g.id === activeGraph().id) b.svg.removeAttribute("hidden");
      else b.svg.setAttribute("hidden", "");
    });
    // A focused node of the graph that just got hidden would keep focus (and
    // the "focus inside" pause) on an invisible element.
    const focused = document.activeElement;
    if (focused && focused.closest && focused.closest("svg[hidden]")) focused.blur();
    syncTabs();
    fitStage();
    renderDetail();
    rearm(); // any graph change (manual or automatic) restarts the 8 s timer
    writeHash();
  }

  function patchRunGraph(b) {
    const loading = S.run.state === "loading";
    const summary = S.run.state === "ready" ? S.run.summary : null;
    b.views.forEach((view, id) => {
      if (view.isError) {
        const text = loading ? "—" : !summary ? "Sin datos de la corrida" : summary.hasFailure ? "La corrida tuvo fallos" : "Sin fallos en la corrida";
        if (view.caption.textContent !== text) view.caption.textContent = text;
        view.g.setAttribute("aria-label", `${view.label}, ${text.toLowerCase()}`);
        return;
      }
      // After a failed load, "no ejecutado" on every node would be a lie: show
      // the neutral "sin datos" look instead.
      if (S.run.state === "error") {
        paintNode(view, { cls: view.traced ? "idle" : "nodata", metric: view.traced ? "—" : null, dot: "○", text: view.traced ? "Sin datos de la corrida" : "Sin datos de nodo" }, `${view.name}, sin datos de la corrida`);
        return;
      }
      patchRunNode(view, summary ? summary.nodes[id] : undefined, loading);
    });
  }

  function patchGraph(graphId) {
    const b = S.built.get(graphId);
    if (!b) return;
    if (S.run) {
      patchRunGraph(b);
      syncSelection(graphId);
      return;
    }
    const loading = S.data === null;
    const nodes = S.data ? S.data.nodes : {};
    let failedTotal = 0;
    Object.values(nodes).forEach((ns) => (failedTotal += ns.failed));
    b.views.forEach((view, id) => {
      if (view.isError) {
        const text = loading
          ? "—"
          : failedTotal === 0
            ? "Sin errores en la ventana"
            : `${plural(failedTotal, "error", "errores")} en la ventana`;
        if (view.caption.textContent !== text) view.caption.textContent = text;
        view.g.setAttribute(
          "aria-label",
          loading
            ? `${view.label}, cargando`
            : `${view.label}, ${failedTotal === 0 ? "sin errores" : plural(failedTotal, "error", "errores")} en la ventana`
        );
        return;
      }
      patchNode(view, nodes[id], loading);
    });
    syncSelection(graphId);
  }

  function syncSelection(graphId) {
    const b = S.built.get(graphId);
    if (!b) return;
    b.views.forEach((view, id) => {
      const on = S.selected[graphId] === id;
      view.g.classList.toggle("agd-selected", on);
      view.g.setAttribute("aria-pressed", String(on));
    });
  }

  function select(nodeId) {
    const g = activeGraph();
    S.selected[g.id] = nodeId;
    syncSelection(g.id);
    renderDetail();
    writeHash();
  }

  // Clicking (or Enter/Space on) a node selects it AND pins the view: the
  // cycle is paused as a manual pause, so it stays paused until resumed.
  function pin(nodeId) {
    if (!S.run) S.play = false; // run mode never cycles: keep the user's intent as is
    select(nodeId);
    rearm();
  }

  // Esc: close the detail panel (back to its placeholder) and clear the selection.
  function clearSelection() {
    const g = activeGraph();
    if (!S.selected[g.id]) return;
    delete S.selected[g.id];
    syncSelection(g.id);
    renderDetail();
    writeHash();
  }

  function outputsOf(graph, nodeId) {
    const ends = new Set(graph.nodes.filter((n) => n.kind === "end").map((n) => n.id));
    const targets = [...new Set(graph.edges.filter((e) => e.from === nodeId).map((e) => e.to))];
    const names = targets.map((t) => (ends.has(t) ? "Fin" : t));
    names.sort((a, b) => (a === "Fin" ? -1 : b === "Fin" ? 1 : a.localeCompare(b)));
    if (!names.length) return "";
    const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} y ${names[names.length - 1]}` : names[0];
    return `Salidas de este nodo: ${list}.`;
  }

  function stat(label, value, extra) {
    const cls = extra ? ` class="${extra}"` : "";
    return `<div class="agd-stat"><span class="agd-stat-label">${ADMIN.escapeHtml(label)}</span><span class="agd-stat-value"${cls}>${ADMIN.escapeHtml(value)}</span></div>`;
  }

  function renderDetail() {
    const panel = $("agd-detail");
    const graph = activeGraph();
    const id = S.selected[graph.id];
    let html;
    if (!id) {
      html = `<p class="muted">Seleccione un nodo del diagrama para ver su detalle.</p>`;
    } else if (S.run) {
      html = runDetailHtml(graph, id);
    } else {
      const node = graph.nodes.find((n) => n.id === id);
      const ns = S.data ? S.data.nodes[id] : undefined;
      const outputs = outputsOf(graph, id);
      let body;
      if (id === ERROR_NODE_ID) {
        let failed = 0;
        Object.values(S.data ? S.data.nodes : {}).forEach((x) => (failed += x.failed));
        body = `<div class="agd-stats">${stat("Fallos en la ventana", S.data ? fmtInt(failed) : "—", failed > 0 ? "agd-bad" : "")}</div>
          <p class="agd-note-text">Recibe el error de cualquier nodo del grafo. No se traza como nodo: sus datos se ven en la lista de errores.</p>
          <div class="agd-links"><a class="link" href="/admin/errors">Ver errores</a></div>`;
      } else if (!node.traced) {
        body = `<p class="agd-note-text">Nodo interno de un subgrafo, sin trazado: no hay datos de ejecución por nodo.</p>`;
      } else if (!S.data) {
        body = `<p class="muted">Cargando…</p>`;
      } else if (!ns || ns.count === 0) {
        body = `<div class="agd-stats">${stat("Ejecuciones", "0")}${stat("Fallos", "0")}${stat("Promedio", "—")}${stat("Mediana (p50)", "—")}</div>
          <p class="agd-note-text">Sin ejecuciones en la ventana.</p>`;
      } else {
        const links = [];
        if (ns.last_run_id) links.push(`<a class="link" href="/admin/runs/${encodeURIComponent(ns.last_run_id)}">Ver última corrida</a>`);
        if (ns.last_error_id) links.push(`<a class="link" href="/admin/errors/${encodeURIComponent(ns.last_error_id)}">Ver último error</a>`);
        body = `<div class="agd-stats">${stat("Ejecuciones", fmtInt(ns.count))}${stat("Fallos", fmtInt(ns.failed), ns.failed > 0 ? "agd-bad" : "")}${stat("Promedio", fmtMs(ns.avg_ms))}${stat("Mediana (p50)", fmtMs(ns.p50_ms))}</div>
          ${links.length ? `<div class="agd-links">${links.join("")}</div>` : ""}`;
      }
      html = `<div class="agd-detail-head"><h2>${ADMIN.escapeHtml(node.label)}</h2><span class="agd-detail-meta" id="agd-detail-meta"></span></div>
        ${body}
        ${outputs ? `<p class="agd-note-text">${ADMIN.escapeHtml(outputs)}</p>` : ""}`;
    }
    // Rewrite the DOM only when the content changed, so links keep focus
    // across polls.
    if (html !== S.detailHtml) {
      panel.innerHTML = html;
      S.detailHtml = html;
    }
    updateMeta();
  }

  // Detail panel in run mode: that run's execution of the node, not aggregates.
  function runDetailHtml(graph, id) {
    const node = graph.nodes.find((n) => n.id === id);
    const head = `<div class="agd-detail-head"><h2>${ADMIN.escapeHtml(node.label)}</h2><span class="agd-detail-meta" id="agd-detail-meta">Corrida ${ADMIN.escapeHtml(shortId(S.run.id))}</span></div>`;
    let body;
    if (id === ERROR_NODE_ID) {
      const errorId = S.run.state === "ready" ? S.run.summary.errorId : null;
      body = `<p class="agd-note-text">Recibe el error de cualquier nodo del grafo. No se traza como nodo.</p>
        <div class="agd-links">${errorId ? `<a class="link" href="/admin/errors/${encodeURIComponent(errorId)}">Ver error de la corrida</a>` : ""}</div>`;
    } else if (!node.traced) {
      body = `<p class="agd-note-text">Nodo interno de un subgrafo, sin trazado: no hay datos de ejecución por nodo.</p>`;
    } else if (S.run.state === "loading") {
      body = `<p class="muted">Cargando…</p>`;
    } else if (S.run.state === "error") {
      body = `<p class="agd-note-text">No hay datos de la corrida.</p>`;
    } else {
      const rs = S.run.summary.nodes[id];
      const d = describeRunNode(rs);
      if (!rs) {
        body = `<div class="agd-stats">${stat("Estado", d.text)}</div>
          <p class="agd-note-text">Este nodo no se ejecutó en esta corrida.</p>`;
      } else {
        const links = [];
        if (rs.errorId) links.push(`<a class="link" href="/admin/errors/${encodeURIComponent(rs.errorId)}">Ver error</a>`);
        const tools = rs.tools.length
          ? `<ul class="agd-tools">${rs.tools
              .map((t) => {
                const bad = t.status === "failed";
                const err = t.error_id ? ` <a class="link" href="/admin/errors/${encodeURIComponent(t.error_id)}">ver error</a>` : "";
                return `<li><span class="${bad ? "agd-bad" : ""}">${bad ? "✗" : "✓"}</span> ${ADMIN.escapeHtml(t.tool_name)} · ${ADMIN.escapeHtml(t.provider)} · ${ADMIN.escapeHtml(t.operation)} <span class="muted">(${ADMIN.escapeHtml(fmtMs(t.duration_ms))})</span>${err}</li>`;
              })
              .join("")}</ul>`
          : "";
        body = `<div class="agd-stats">${stat("Estado", d.text, rs.status === "fail" ? "agd-bad" : "")}${stat("Duración", fmtMs(rs.durationMs))}${rs.count > 1 ? stat("Ejecuciones", fmtInt(rs.count)) : ""}</div>
          ${links.length ? `<div class="agd-links">${links.join("")}</div>` : ""}
          ${tools}`;
      }
    }
    const outputs = outputsOf(graph, id);
    return `${head}
      ${body}
      ${outputs ? `<p class="agd-note-text">${ADMIN.escapeHtml(outputs)}</p>` : ""}`;
  }

  const shortId = (id) => String(id || "").slice(0, 8);

  function lastRunAgeSeconds(ns) {
    const lastMs = Date.parse(ns.last_at);
    if (Number.isNaN(lastMs)) return null;
    return (S.generatedMs - lastMs) / 1000 + (Date.now() - S.fetchedAt) / 1000;
  }

  function updateMeta() {
    const meta = $("agd-detail-meta");
    if (!meta || S.run) return;
    const id = S.selected[activeGraph().id];
    const ns = S.data && id ? S.data.nodes[id] : undefined;
    let text = `Ventana: ${WINDOW_PHRASE[S.win]}`;
    if (ns && ns.count > 0) {
      const age = lastRunAgeSeconds(ns);
      if (age !== null) text += ` · última ejecución ${fmtAgo(age)}`;
    }
    if (meta.textContent !== text) meta.textContent = text;
  }

  function updateIndicator() {
    const el = $("agd-updated");
    const dot = $("agd-updated-dot");
    const text = $("agd-updated-text");
    el.classList.toggle("agd-stale", S.stale && !S.run);
    if (S.run) {
      dot.textContent = "○";
      text.textContent = "Corrida fija, sin actualización en vivo";
      return;
    }
    if (!S.data) {
      dot.textContent = "○";
      text.textContent = S.stale ? "Sin datos" : "Cargando…";
      return;
    }
    const ago = fmtAgo((Date.now() - S.fetchedAt) / 1000);
    dot.textContent = S.stale ? "▲" : "●";
    text.textContent = S.stale ? `Desactualizado: último dato ${ago}` : `Actualizado ${ago}`;
  }

  function updateStatusRow() {
    const row = $("agd-status");
    let msg = "";
    if (S.run) {
      if (S.run.state === "ready" && Object.keys(S.run.summary.nodes).length === 0) msg = "La corrida no registró nodos.";
    } else if (S.data) {
      const reportable = Object.keys(S.data.nodes).length === 0;
      if (reportable) msg = "Sin ejecuciones en la ventana";
      else if (S.data.truncated) msg = "La ventana tiene más ejecuciones de las que se analizan: los números son parciales.";
    }
    if (row.textContent !== msg) row.textContent = msg;
  }

  function applyData(data) {
    S.data = data;
    S.fetchedAt = Date.now();
    const g = Date.parse(data.generated_at);
    S.generatedMs = Number.isNaN(g) ? S.fetchedAt : g;
    S.stale = false;
    showBanner("");
    S.built.forEach((_, id) => patchGraph(id));
    updateStatusRow();
    updateIndicator();
    renderDetail();
  }

  // -------------------------------------------------------------- polling --

  function stopPolling() {
    clearTimeout(S.timer);
    S.timer = null;
    S.generation++; // drops any response still in flight
    if (S.controller) S.controller.abort();
    S.controller = null;
  }

  function schedule(ms) {
    clearTimeout(S.timer);
    S.timer = null;
    if (!document.hidden) S.timer = setTimeout(poll, ms);
  }

  async function poll() {
    if (S.run) return;
    clearTimeout(S.timer);
    if (S.controller) S.controller.abort();
    const controller = new AbortController();
    S.controller = controller;
    const generation = ++S.generation;
    try {
      const response = await ADMIN.apiFetch(`/graphs/state?window=${encodeURIComponent(S.win)}`, {
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (generation !== S.generation) return;
      applyData(data);
      schedule(POLL_MS);
    } catch (err) {
      if (generation !== S.generation || (err && err.name === "AbortError")) return;
      S.stale = true;
      showBanner(
        S.data
          ? "No se pudo actualizar el estado. Se muestran los últimos datos recibidos y se reintenta cada 30 s."
          : "No se pudo cargar el estado del agente. Se reintenta cada 30 s."
      );
      updateIndicator();
      schedule(BACKOFF_MS);
    }
  }

  function setWindow(win) {
    if (win === S.win) return;
    S.win = win;
    syncWindowButtons();
    writeHash();
    if (S.run) return; // the window only applies to the live aggregates
    // The old numbers belong to another window: show them as loading until the
    // new payload arrives (stale responses are dropped by the generation guard).
    S.data = null;
    S.built.forEach((_, id) => patchGraph(id));
    updateStatusRow();
    updateIndicator();
    renderDetail();
    poll();
  }

  function syncWindowButtons() {
    document.querySelectorAll("#agd-window button").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.window === S.win));
    });
  }

  // -------------------------------------------------------------- run mode --

  function cancelRunLoad() {
    S.runSeq++;
    if (S.runController) S.runController.abort();
    S.runController = null;
  }

  function enterRun(run) {
    cancelRunLoad();
    stopPolling(); // no live polling while a run is shown
    S.run = run;
  }

  // Leaves run mode state-wise; the caller refreshes the UI and restarts polling.
  function exitRunState() {
    cancelRunLoad();
    S.run = null;
    S.data = null; // pre-run numbers would be stale: show loading until the next poll
  }

  function failRun(message) {
    S.run.state = "error";
    S.run.message = message;
    syncRunUi();
  }

  async function loadRun() {
    const run = S.run;
    cancelRunLoad();
    const seq = S.runSeq;
    const controller = new AbortController();
    S.runController = controller;
    try {
      const response = await ADMIN.apiFetch(`/runs/${encodeURIComponent(run.id)}`, { signal: controller.signal });
      if (seq !== S.runSeq) return;
      if (!response.ok) {
        failRun(
          response.status === 404
            ? "No se encontró esa corrida. Verifique el identificador."
            : response.status === 403
              ? "No tiene permiso para ver esa corrida."
              : `No se pudo cargar la corrida (HTTP ${response.status}).`
        );
        return;
      }
      const summary = summarizeRun(await response.json());
      if (seq !== S.runSeq) return;
      run.summary = summary;
      run.state = "ready";
      const pending = run.pending || {};
      S.applying = true;
      try {
        if (pending.autoGraph) {
          const idx = pickRunGraph(S.graphs, Object.keys(summary.nodes), undefined);
          const target = S.graphs[idx];
          if (pending.focus !== undefined && !S.selected[target.id] && S.built.get(target.id).views.has(pending.focus)) {
            S.selected[target.id] = pending.focus;
          }
          setActive(idx);
        }
      } finally {
        S.applying = false;
      }
      syncRunUi();
      writeHash();
    } catch (err) {
      if (seq !== S.runSeq || (err && err.name === "AbortError")) return;
      failRun("No se pudo cargar la corrida. Compruebe la conexión y recargue la página.");
    }
  }

  const RUN_STATUS_TEXT = { completed: "OK", failed: "Fallo", running: "En curso" };

  // Repaints everything that depends on live-vs-run mode.
  function syncRunUi() {
    const run = S.run;
    const main = document.querySelector(".agd-main");
    if (main) main.classList.toggle("agd-run-mode", !!run);
    document.querySelectorAll("#agd-window button").forEach((btn) => {
      btn.disabled = !!run;
    });
    const bar = $("agd-runbar");
    bar.hidden = !run;
    if (run) {
      const failed = run.state === "error";
      bar.classList.toggle("agd-runbar-error", failed);
      bar.setAttribute("role", failed ? "alert" : "status");
      $("agd-runbar-title").textContent = run.id ? `Corrida ${shortId(run.id)}` : "Corrida";
      let meta;
      if (failed) meta = run.message;
      else if (run.state === "loading") meta = "Cargando…";
      else {
        const parts = [`Iniciada ${ADMIN.formatDateTime(run.summary.startedAt)}`];
        if (RUN_STATUS_TEXT[run.summary.status]) parts.push(`Estado: ${RUN_STATUS_TEXT[run.summary.status]}`);
        meta = parts.join(" · ");
      }
      $("agd-runbar-meta").textContent = meta;
    }
    S.built.forEach((_, id) => patchGraph(id));
    updateStatusRow();
    updateIndicator();
    renderDetail();
  }

  // "Volver al estado en vivo": drop `run` from the URL and resume polling.
  function leaveRun() {
    if (!S.run) return;
    exitRunState();
    syncRunUi();
    rearm();
    writeHash();
    poll();
    const tab = S.graphs.length ? $(`agd-tab-${activeGraph().id}`) : null;
    if (tab) tab.focus();
  }

  // ----------------------------------------------------- cycle, hash, keys --

  const CYCLE_NOTES = {
    run: () => "Sin recorrido automático en la vista de una corrida",
    running: () => `Cambia de grafo cada ${Math.round(S.cycleMs / 1000)} s`,
    hover: () => "En pausa mientras el cursor está sobre el diagrama",
    focus: () => "En pausa mientras el foco está en el diagrama",
  };

  function syncPlayControls(state) {
    const btn = $("agd-play");
    btn.textContent = S.play ? "⏸ Pausar recorrido" : "▶ Reanudar recorrido";
    btn.setAttribute("aria-pressed", String(!S.play));
    btn.disabled = S.graphs.length < 2 || !!S.run;
    const note = CYCLE_NOTES[state];
    const text = note ? note() : "";
    if ($("agd-cycle-note").textContent !== text) $("agd-cycle-note").textContent = text;
  }

  // (Re)starts the one-shot cycle timer from zero if the cycle should be
  // ticking, otherwise clears it. Called on every change that can affect the
  // cycle, which is also what restarts the 8 s countdown after a manual action.
  function rearm() {
    clearTimeout(S.cycleTimer);
    S.cycleTimer = null;
    const state = cycleState({
      play: S.play,
      hovering: S.hovering,
      focusInside: S.focusInside,
      hidden: document.hidden,
      graphCount: S.graphs.length,
      runMode: !!S.run,
    });
    if (state === "running") {
      S.cycleTimer = setTimeout(() => setActive(nextIndex(S.active, 1, S.graphs.length)), S.cycleMs);
    }
    syncPlayControls(state);
  }

  function setPlay(on) {
    S.play = on;
    rearm();
    writeHash();
  }

  // Writes the state to the URL with replaceState (no history entries, no
  // hashchange event). Skipped until the initial hash has been applied so a
  // failed load does not clobber the incoming hash.
  function writeHash() {
    if (!S.ready || S.applying || !S.graphs.length) return;
    const g = activeGraph();
    // The run id is kept even when its load failed, so the URL stays what the
    // user opened until they leave run mode. A malformed run id has no id to keep.
    const hash = serializeHash({ g: g.id, focus: S.selected[g.id], w: S.win, play: S.run ? undefined : S.play, run: S.run && S.run.id });
    if (hash === location.hash) return;
    try {
      history.replaceState(null, "", `${location.pathname}${location.search}${hash}`);
    } catch (e) {
      // Some embedded contexts forbid it; the page works without URL state.
    }
  }

  // Applies a parsed hash as the full view state: absent or invalid parts fall
  // back to defaults. `focus` selects that node and implies play=0. On the
  // initial load reduced motion always wins over play=1; a later hashchange is
  // an explicit user edit and is honoured as written.
  function applyHash(h, initial) {
    S.applying = true;
    const wasRun = !!S.run;
    try {
      // Run state first: setWindow/setActive below consult it.
      if (h.run && S.run && S.run.id === h.run && S.run.state === "ready") {
        // Same run already loaded (e.g. only `w` or `focus` changed): keep it.
      } else if (h.run || h.runInvalid) {
        enterRun(h.run ? { id: h.run, state: "loading", summary: null, message: "" } : { id: null, state: "error", summary: null, message: "El identificador de corrida de la URL no es válido." });
      } else if (wasRun) {
        exitRunState();
      }
      const gi = S.graphs.findIndex((g) => g.id === h.g);
      const graph = S.graphs[gi >= 0 ? gi : 0];
      if (S.run && S.run.state === "loading") S.run.pending = { autoGraph: gi < 0, focus: h.focus };
      const win = h.w || DEFAULT_WINDOW;
      if (initial) {
        S.win = win;
        syncWindowButtons();
      } else {
        setWindow(win);
      }
      S.selected = {};
      const focusOk = h.focus !== undefined && S.built.get(graph.id).views.has(h.focus);
      if (focusOk) S.selected[graph.id] = h.focus;
      setActive(S.graphs.indexOf(graph));
      S.built.forEach((_, id) => syncSelection(id));
      if (focusOk) S.play = false;
      else if (h.play === undefined) S.play = !S.reduced;
      else S.play = initial && S.reduced ? false : h.play;
    } finally {
      S.applying = false;
    }
    syncRunUi();
    rearm();
    writeHash();
    if (S.run && S.run.state === "loading") loadRun();
    else if (!S.run && wasRun) poll();
  }

  const isTextControl = (el) =>
    !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

  // Page-level shortcuts. The listener sits on `document` only because a focused
  // <body> is not inside the page container; it ignores every event whose target
  // is outside <main> (topbar, logout) or body, and any text/select control, so
  // it never fires while typing or on controls it does not own.
  //   Left/Right: previous/next graph.  Space: play/pause, only when focus is on
  //   body or the diagram region itself (never on a button/link/node: those
  //   keep their own Space behaviour).  Esc: clear selection / close detail.
  function onKeydown(event) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || !S.graphs.length) return;
    const t = event.target;
    const onBody = t === document.body || t === document.documentElement;
    if (!onBody && !(t.closest && t.closest(".agd-main"))) return;
    if (isTextControl(t)) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setActive(nextIndex(S.active, event.key === "ArrowLeft" ? -1 : 1, S.graphs.length));
    } else if (event.key === " ") {
      if (S.run) return;
      const onRegion = onBody || (t.id === "agd-stage" || t.id === "agd-canvas" || t.classList.contains("agd-svg"));
      if (!onRegion) return;
      event.preventDefault();
      if (!event.repeat) setPlay(!S.play);
    } else if (event.key === "Escape") {
      clearSelection();
    }
  }

  // ----------------------------------------------------------------- init --

  async function loadTopology() {
    showBanner("");
    $("agd-canvas").setAttribute("aria-busy", "true");
    let graphs;
    try {
      const response = await ADMIN.apiFetch("/graphs");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      graphs = (await response.json()).graphs;
    } catch (err) {
      showBanner("No se pudieron cargar los grafos del agente.", loadTopology);
      return;
    }
    S.graphs = graphs;
    $("agd-skeleton").hidden = true;
    $("agd-canvas").setAttribute("aria-busy", "false");
    renderTabs();
    S.graphs.forEach(ensureBuilt);
    S.ready = true;
    applyHash(parseHash(location.hash), true);
    if (!S.run) poll();
  }

  async function init() {
    const me = await ADMIN.requireAuth();
    $("who-label").textContent = `${me.username} · ${me.role}`;
    $("logout-btn").addEventListener("click", ADMIN.logout);

    $("agd-prev").addEventListener("click", () => S.graphs.length && setActive(nextIndex(S.active, -1, S.graphs.length)));
    $("agd-next").addEventListener("click", () => S.graphs.length && setActive(nextIndex(S.active, 1, S.graphs.length)));
    $("agd-play").addEventListener("click", () => setPlay(!S.play));
    $("agd-run-exit").addEventListener("click", leaveRun);
    document.querySelectorAll("#agd-window button").forEach((btn) => {
      btn.addEventListener("click", () => setWindow(btn.dataset.window));
    });
    syncWindowButtons();

    const canvas = $("agd-canvas");
    const pick = (event) => {
      const g = event.target.closest("[data-node-id]");
      if (g) pin(g.getAttribute("data-node-id"));
    };
    canvas.addEventListener("click", pick);
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(() => S.graphs.length && fitStage()).observe(canvas);
    else window.addEventListener("resize", () => S.graphs.length && fitStage());
    canvas.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (!event.repeat) pick(event);
      }
    });

    // Pause the cycle while the pointer is over the diagram or focus is in it.
    const stage = $("agd-stage");
    stage.addEventListener("mouseenter", () => {
      S.hovering = true;
      rearm();
    });
    stage.addEventListener("mouseleave", () => {
      S.hovering = false;
      rearm();
    });
    stage.addEventListener("focusin", () => {
      S.focusInside = true;
      rearm();
    });
    stage.addEventListener("focusout", (event) => {
      if (event.relatedTarget && stage.contains(event.relatedTarget)) return;
      S.focusInside = false;
      rearm();
    });

    document.addEventListener("keydown", onKeydown);
    window.addEventListener("hashchange", () => {
      if (S.ready) applyHash(parseHash(location.hash), false);
    });

    S.cycleMs = Number(globalThis.__AGD_CYCLE_MS) > 0 ? Number(globalThis.__AGD_CYCLE_MS) : CYCLE_MS; // test hook
    try {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      S.reduced = mq.matches;
      S.play = !S.reduced;
      // Turning reduced motion on mid-session stops the cycle; turning it off
      // never starts one by itself.
      const onMotion = (event) => {
        S.reduced = event.matches;
        if (S.reduced) setPlay(false);
      };
      if (mq.addEventListener) mq.addEventListener("change", onMotion);
      else if (mq.addListener) mq.addListener(onMotion);
    } catch (e) {
      S.reduced = false;
    }

    document.addEventListener("visibilitychange", () => {
      rearm();
      if (document.hidden) {
        clearTimeout(S.timer);
        S.generation++;
        if (S.controller) S.controller.abort();
      } else if (S.graphs.length && !S.run) {
        poll();
      }
    });
    setInterval(() => {
      updateIndicator();
      updateMeta();
    }, 1000);

    updateIndicator();
    await loadTopology();
  }

  return {
    init,
    computeLayout,
    splitName,
    fmtInt,
    fmtMs,
    fmtAgo,
    parseHash,
    serializeHash,
    nextIndex,
    cycleState,
    nodeAriaLabel,
    summarizeRun,
    pickRunGraph,
    describeRunNode,
    runNodeAriaLabel,
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = AgentDiagram;
}
if (typeof document !== "undefined" && document.getElementById("agd-stage")) {
  AgentDiagram.init();
}
