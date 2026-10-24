"use strict";

const MAX_PLOTTED = 5;
const WINDOW_S = 300;
const GAP_BREAK_S = 10;
const STRONG = -60, MEDIUM = -75;

const state = {
  snap: null,
  meta: {},
  selected: null,
  plotted: new Map(),   // id -> slot (1..5); el color sigue a la entidad, no a su posición
  series: new Map(),    // id -> [[t_sec, rssi], ...]
  sortKey: "rssi",
  sortAsc: false,
  hoverX: null,
  autoPlot: true,       // hasta que el usuario marque una fila: graficar las 3 señales más fuertes
};
const AUTO_PLOT_N = 3;

// ---------- utilidades DOM (siempre textContent, nunca innerHTML con datos) ----------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);
const short = (e) => e.lab_id || e.id.slice(0, 6);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const seriesColor = (slot) => cssVar(`--s${slot}`);
const toSec = (iso) => Date.parse(iso) / 1000;

function ago(iso) {
  if (!state.snap) return "";
  const s = Math.max(0, Math.round(toSec(state.snap.t) - toSec(iso)));
  if (s < 60) return `hace ${s} s`;
  return `hace ${Math.floor(s / 60)} min`;
}

// ---------- datos ----------
async function loadMeta() {
  try {
    const res = await fetch("/api/state");
    const data = await res.json();
    state.meta = data.meta || {};
    onSnapshot(data);
  } catch (err) { /* el WebSocket reintenta */ }
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (ev) => onSnapshot(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connect, 2000);
}

function onSnapshot(snap) {
  state.snap = snap;
  const t = toSec(snap.t);
  const byId = new Map(snap.entities.map((e) => [e.id, e]));
  if (state.autoPlot) {
    const top = snap.entities.filter((e) => e.present && e.rssi !== null)
      .sort((a, b) => b.rssi - a.rssi).slice(0, AUTO_PLOT_N).map((e) => e.id);
    for (const id of [...state.plotted.keys()]) if (!top.includes(id)) togglePlot(id, true);
    for (const id of top) if (!state.plotted.has(id)) togglePlot(id, true);
  }
  for (const [id] of state.plotted) {
    const e = byId.get(id);
    const pts = state.series.get(id) || [];
    if (e && e.present && e.rssi !== null) {
      const last = pts[pts.length - 1];
      if (!last || t > last[0]) pts.push([t, e.rssi]);
    }
    while (pts.length && pts[0][0] < t - WINDOW_S) pts.shift();
    state.series.set(id, pts);
  }
  render();
}

async function togglePlot(id, auto = false) {
  if (!auto && state.autoPlot) {
    state.autoPlot = false;
    state.plotted.clear();
    state.series.clear();
  }
  if (state.plotted.has(id)) {
    state.plotted.delete(id);
    state.series.delete(id);
  } else {
    if (state.plotted.size >= MAX_PLOTTED) return;
    const used = new Set(state.plotted.values());
    let slot = 1;
    while (used.has(slot)) slot++;
    state.plotted.set(id, slot);
    try {
      const res = await fetch(`/api/entities/${encodeURIComponent(id)}/history`);
      const data = await res.json();
      state.series.set(id, data.points.map(([s, v]) => [s, v]));
    } catch (err) {
      state.series.set(id, []);
    }
  }
  render();
}

async function saveLabel(id, labId) {
  await fetch(`/api/entities/${encodeURIComponent(id)}/label`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lab_id: labId || null }),
  });
}

// ---------- filtros y orden ----------
const LABEL_ORDER = { auricular: 0, parlante: 1, insuficiente: 2, desconocido: 3 };
const CONF_ORDER = { alta: 0, media: 1, baja: 2 };
const SORTERS = {
  plot: (e) => (state.plotted.has(e.id) ? 0 : 1),
  present: (e) => (e.present ? 0 : 1),
  id: (e) => short(e),
  label: (e) => LABEL_ORDER[e.label],
  confidence: (e) => CONF_ORDER[e.confidence] ?? 9,
  family: (e) => e.model || e.family || "~",
  rssi: (e) => (e.rssi === null ? -999 : e.rssi),
  dist: (e) => (e.distance ? e.distance.nominal : 1e9),
  trend: (e) => e.trend || "~",
  packets: (e) => e.packets,
  last_seen: (e) => e.last_seen,
};

function filtered(entities) {
  const text = $("#f-text").value.trim().toLowerCase();
  const label = $("#f-label").value;
  const minRssi = Number($("#f-rssi").value);
  const hideAbsent = $("#f-present").checked;
  return entities.filter((e) => {
    if (hideAbsent && !e.present) return false;
    if (label === "audio" && !(e.label === "auricular" || e.label === "parlante")) return false;
    if (label && label !== "audio" && e.label !== label) return false;
    if (minRssi > -110 && (e.rssi === null || e.rssi < minRssi)) return false;
    if (text) {
      const hay = [e.id, e.lab_id, e.family, e.model].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  });
}

function sorted(entities) {
  const key = SORTERS[state.sortKey];
  const dir = state.sortAsc ? 1 : -1;
  return [...entities].sort((a, b) => {
    const ka = key(a), kb = key(b);
    if (ka < kb) return -1 * dir;
    if (ka > kb) return 1 * dir;
    return 0;
  });
}

// ---------- render ----------
function render() {
  if (!state.snap) return;
  renderStats();
  renderAlerts();
  renderRadar();
  renderSearchControls();
  renderPlan();
  renderTable();
  renderDetail();
  renderEvents();
  drawChart();
}

function renderStats() {
  const s = state.snap;
  const mins = Math.round((toSec(s.t) - toSec(s.started)) / 60);
  $("#stats").replaceChildren(...[
    h("span", {}, h("b", {}, s.entities_present), " presentes / ", s.entities_total, " entidades"),
    h("span", {}, h("b", {}, s.packets.toLocaleString("es")), " paquetes"),
    h("span", {}, "fuentes: ", s.backends.join(", ") || "—"),
    h("span", {}, `sesión: ${mins} min`),
    s.dropped ? h("span", {}, h("b", {}, s.dropped), " descartados (cola llena)") : null,
  ].filter(Boolean));
}

function renderAlerts() {
  const items = [];
  if (state.snap.spam_active) {
    items.push(h("div", { class: "alert warning" }, h("span", { class: "icon" }, "⚠ Posible BLE spam"),
      "Muchas direcciones distintas emiten Proximity Pairing de Apple a la vez. Las clasificaciones Apple de este momento no son confiables."));
  }
  const adapter = state.meta.adapter || {};
  if (adapter.is_extended_advertising_supported === false) {
    items.push(h("div", { class: "alert" }, h("span", { class: "icon" }, "ℹ"),
      "Este adaptador no recibe anuncios extendidos: LE Audio / Auracast no son visibles desde esta PC."));
  }
  $("#alerts").replaceChildren(...items);
}

function renderTable() {
  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.classList.toggle("sorted", th.dataset.sort === state.sortKey);
    th.classList.toggle("asc", th.dataset.sort === state.sortKey && state.sortAsc);
  }
  const rows = sorted(filtered(state.snap.entities)).map((e) => {
    const slot = state.plotted.get(e.id);
    const isAudio = e.label === "auricular" || e.label === "parlante";
    const check = h("input", {
      type: "checkbox", checked: Boolean(slot),
      disabled: !slot && state.plotted.size >= MAX_PLOTTED,
      "aria-label": `Graficar ${short(e)}`,
      onclick: (ev) => { ev.stopPropagation(); togglePlot(e.id); },
    });
    const signal = e.rssi === null ? "—" : `${e.signal} · ${Math.round(e.rssi)} dBm`;
    const dist = e.distance ? e.distance.text : "—";
    return h("tr", {
      class: [e.present ? "" : "absent", state.selected === e.id ? "selected" : ""].join(" "),
      onclick: () => { state.selected = e.id; history.replaceState(null, "", `#e=${e.id}`); render(); },
    },
      h("td", { class: "narrow" }, check, slot ? h("span", { class: "key", style: `background:${seriesColor(slot)};margin-left:4px` }) : null),
      h("td", {}, h("span", { class: `dot ${e.present ? "on" : ""}` }), e.present ? "presente" : "ausente"),
      h("td", { class: "mono" }, short(e), e.transport === "bredr" ? " · Classic" : ""),
      h("td", {}, h("span", { class: `badge ${isAudio ? "audio" : ""}` }, e.label_text),
        e.basis ? h("span", { class: "basis" }, e.basis) : null,
        e.warnings.length ? h("span", { class: "warn-mark", title: e.warnings.join("\n") }, "⚠") : null),
      h("td", {}, e.confidence || "—"),
      h("td", { class: "wrap" }, e.model ? `${e.model}` : (e.family || "—")),
      h("td", { class: "num" }, signal),
      h("td", { class: "num" }, dist),
      h("td", {}, e.trend || "—"),
      h("td", { class: "num" }, e.packets.toLocaleString("es")),
      h("td", {}, ago(e.last_seen)),
    );
  });
  $("#table tbody").replaceChildren(...rows);
}

function renderDetail() {
  const box = $("#detail");
  const e = state.snap.entities.find((x) => x.id === state.selected);
  if (!e) {
    box.replaceChildren(h("p", { class: "muted" }, "Seleccioná una fila para ver por qué se clasificó así."));
    return;
  }
  const active = document.activeElement;
  const editing = active && box.contains(active) && ["INPUT", "SELECT"].includes(active.tagName);
  if (editing && box.dataset.entity === e.id) return; // no pisar lo que se está escribiendo o eligiendo
  box.dataset.entity = e.id;

  const labInput = h("input", { id: "lab-input", placeholder: "LAB-A01 (solo dispositivos propios)", value: e.lab_id || "" });
  const reasons = e.reasons.length ? e.reasons.map((r) => h("div", { class: "reason" },
    h("div", { class: "rhead" }, h("b", {}, r.rule), h("span", { class: "badge" }, r.level),
      r.type ? h("span", { class: "small" }, `→ ${r.type}`) : null,
      h("span", { class: "small" }, `${r.packets} paquetes`),
      h("span", { class: "small" }, r.validated ? "validada en laboratorio" : "no validada en laboratorio")),
    h("div", {}, r.detail),
    h("div", { class: "small" }, "Fuente: ", r.source),
    r.false_positives ? h("div", { class: "small" }, "Falsos positivos conocidos: ", r.false_positives) : null,
  )) : [h("p", { class: "muted" }, "Ninguna regla encontró evidencia en los paquetes de esta entidad.")];

  box.replaceChildren(
    h("h2", {}, e.label_text),
    h("p", {}, e.basis === "declarado"
      ? "Declarado: un campo del anuncio afirma el tipo. Ningún anuncio está autenticado."
      : e.basis === "hipótesis" ? "Hipótesis: basada solo en indicios (nombre, servicio no exclusivo)." : ""),
    ...e.warnings.map((w) => h("div", { class: "warnbox" }, "⚠ ", w)),
    h("dl", {},
      h("dt", {}, "Entidad"), h("dd", { class: "mono" }, e.id),
      h("dt", {}, "Confianza"), h("dd", {}, e.confidence || "—"),
      h("dt", {}, "Modelo declarado"), h("dd", {}, e.model || "—"),
      h("dt", {}, "Familia"), h("dd", {}, e.family || "—"),
      h("dt", {}, "Señal"), h("dd", {}, e.rssi === null ? "—" : `${e.signal} (${e.rssi} dBm suavizado, último ${e.rssi_last}, dispersión ${e.spread ?? "—"} dB)`),
      h("dt", {}, "Distancia aprox."), h("dd", {}, e.distance ? e.distance.text : "—",
        e.distance && !e.distance.calibrated ? h("div", { class: "small muted" }, "Calibrá este dispositivo a 1 m para achicar el intervalo. A través de paredes el número es muy incierto: manda la atenuación, no la distancia.") : null),
      h("dt", {}, "Tendencia"), h("dd", {}, e.trend || "datos insuficientes"),
      h("dt", {}, "Dirección"), h("dd", {}, `${e.transport === "bredr" ? "Classic" : "BLE"} · ${e.address_kind}`),
      h("dt", {}, "Paquetes"), h("dd", {}, `${e.packets} (${e.rate}/s) · ${Object.entries(e.pdus).map(([k, v]) => `${k}: ${v}`).join(", ")}`),
      h("dt", {}, "Fabricantes (CID)"), h("dd", {}, e.companies.join(", ") || "—"),
      h("dt", {}, "Apple Continuity"), h("dd", {}, e.apple_types.join(", ") || "—"),
      h("dt", {}, "Nombre"), h("dd", {}, e.has_name ? `presente (descartado)${e.name_hint ? `, indicio: ${e.name_hint}` : ""}` : "no anunciado"),
      h("dt", {}, "Visto"), h("dd", {}, `${new Date(e.first_seen).toLocaleTimeString("es")} → ${new Date(e.last_seen).toLocaleTimeString("es")}`),
    ),
    h("h2", {}, "Por qué"),
    ...reasons,
    h("h2", {}, "Etiqueta de laboratorio"),
    h("div", { class: "lab" }, labInput,
      h("button", { class: "btn", onclick: () => saveLabel(e.id, labInput.value.trim()) }, "Guardar")),
    h("p", { class: "small muted" }, "Asigná un LAB-ID solo a dispositivos propios. Se guarda en los metadatos de la sesión."),
    ...calibrationBlock(e),
  );
}

function calibrationBlock(e) {
  const room = state.snap.room;
  if (!room || !e.lab_id) return [];
  const select = h("select", { id: "calib-node" }, ...Object.keys(room.nodes).map((id) => h("option", { value: id }, id)));
  const dist = h("input", { id: "calib-dist", type: "number", min: "0.2", step: "0.1", value: "1" });
  const out = h("span", { class: "small" });
  return [
    h("h2", {}, "Calibración"),
    h("p", { class: "small muted" }, "Poné este dispositivo a una distancia medida del receptor, en línea de vista, esperá ~15 s y calibrá. Repetí para cada receptor."),
    h("div", { class: "calib" }, select, dist, "m",
      h("button", { class: "btn", onclick: () => calibrate(e.id, select.value, Number(dist.value), out) }, "Calibrar"), out),
  ];
}

function renderEvents() {
  const items = [...state.snap.events].reverse().map((ev) =>
    h("li", {}, `${new Date(ev.t).toLocaleTimeString("es")} · ${ev.event}`, ev.entity ? ` · ${ev.entity.slice(0, 6)}` : "", ev.detail ? ` · ${ev.detail}` : ""));
  $("#events").replaceChildren(...items);
}

// ---------- mapa de señal (radar) ----------
// Radio = intensidad de señal (no metros). Ángulo = cuadrante de la clasificación + posición
// estable derivada del pseudónimo, para que los puntos no salten. No representa dirección.
const SVGNS = "http://www.w3.org/2000/svg";
const RADAR = { c: 200, R: 165, near: -30, far: -100 };
const SECTORS = {
  auricular: { start: -90, label: "Posibles auriculares", color: "var(--s1)", x: 396, y: 14, anchor: "end" },
  parlante: { start: 0, label: "Posibles parlantes", color: "var(--s2)", x: 396, y: 394, anchor: "end" },
  insuficiente: { start: 90, label: "Clasificación insuficiente", color: "var(--muted)", x: 4, y: 394, anchor: "start" },
  desconocido: { start: 180, label: "Desconocidos", color: "var(--muted)", x: 4, y: 14, anchor: "start" },
};
const radarNodes = new Map(); // id -> {g, band}
const sectorLabels = {};

function svg(tag, attrs = {}) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

const radarR = (rssi) => RADAR.R * Math.min(1, Math.max(0.06, (RADAR.near - rssi) / (RADAR.near - RADAR.far)));

function initRadar() {
  const root = $("#radar");
  const { c, R } = RADAR;
  const base = svg("g");
  base.append(svg("circle", { cx: c, cy: c, r: R, class: "radar-ring" }));
  for (const [v, name] of [[STRONG, "fuerte"], [MEDIUM, "media"]]) {
    base.append(svg("circle", { cx: c, cy: c, r: radarR(v), class: "radar-ring threshold" }));
    const t = svg("text", { x: c + 4, y: c - radarR(v) + 12 });
    t.textContent = `${name} (≥ ${v} dBm)`;
    base.append(t);
  }
  const weak = svg("text", { x: c + 4, y: c - R + 12 });
  weak.textContent = `débil (< ${MEDIUM} dBm)`;
  base.append(weak);
  base.append(svg("line", { x1: c - R, y1: c, x2: c + R, y2: c, class: "radar-divider" }));
  base.append(svg("line", { x1: c, y1: c - R, x2: c, y2: c + R, class: "radar-divider" }));
  for (const [key, s] of Object.entries(SECTORS)) {
    const t = svg("text", { x: s.x, y: s.y, "text-anchor": s.anchor, class: "sector" });
    sectorLabels[key] = t;
    base.append(t);
  }
  base.append(svg("circle", { cx: c, cy: c, r: 4, style: "fill: var(--text)" }));
  const pc = svg("text", { x: c, y: c + 18, "text-anchor": "middle" });
  pc.textContent = "esta PC";
  base.append(pc);
  root.append(base, svg("g", { id: "radar-dots" }));

  $("#radar-legend").replaceChildren(
    ...[["var(--s1)", "posible auricular"], ["var(--s2)", "posible parlante"], ["var(--muted)", "desconocido / insuficiente"]]
      .map(([color, text]) => h("span", {}, h("span", { class: "dotkey", style: `background:${color}` }), text)),
    h("span", {}, "barra radial = dispersión del RSSI · punto tenue = ausente"),
  );
}

function stableFraction(id) {
  return parseInt(id.slice(0, 6), 16) / 0xffffff;
}

function showRadarTip(ev, e) {
  const tip = $("#radar-tip");
  const wrap = $(".radar-wrap").getBoundingClientRect();
  tip.replaceChildren(
    h("div", { class: "row" }, h("span", { class: "val" }, e.rssi === null ? "—" : `${Math.round(e.rssi)} dBm`), `señal ${e.signal || "—"}`),
    e.distance ? h("div", { class: "when" }, e.distance.text) : null,
    h("div", {}, `${short(e)} · ${e.label_text}${e.basis ? ` (${e.basis})` : ""}`),
    h("div", { class: "when" }, e.model || e.family || "sin familia"),
    h("div", { class: "when" }, `${e.trend || "tendencia: datos insuficientes"} · ${e.present ? "presente" : "ausente"}`),
  );
  tip.hidden = false;
  const x = (ev.clientX ?? wrap.left + wrap.width / 2) - wrap.left;
  const y = (ev.clientY ?? wrap.top + wrap.height / 2) - wrap.top;
  tip.style.left = `${Math.min(x + 12, wrap.width - tip.offsetWidth)}px`;
  tip.style.top = `${y + 12}px`;
}

function renderRadar() {
  const layer = $("#radar-dots");
  const visible = filtered(state.snap.entities).filter((e) => e.rssi !== null);
  const counts = { auricular: 0, parlante: 0, insuficiente: 0, desconocido: 0 };
  const seen = new Set();
  for (const e of visible) {
    const sector = SECTORS[e.label];
    counts[e.label] += 1;
    seen.add(e.id);
    let node = radarNodes.get(e.id);
    if (!node) {
      const g = svg("g", { class: "radar-entity", tabindex: "0" });
      const band = svg("line", { class: "band", y1: 0, y2: 0 });
      g.append(band, svg("circle", { r: 12, style: "fill: transparent" }), svg("circle", { class: "dot", r: 6 }));
      g.addEventListener("click", () => { state.selected = node.id; history.replaceState(null, "", `#e=${node.id}`); render(); });
      g.addEventListener("pointermove", (ev) => showRadarTip(ev, node.entity));
      g.addEventListener("focus", (ev) => showRadarTip(ev, node.entity));
      g.addEventListener("pointerleave", () => { $("#radar-tip").hidden = true; });
      g.addEventListener("blur", () => { $("#radar-tip").hidden = true; });
      node = { id: e.id, g, band };
      radarNodes.set(e.id, node);
      layer.append(g);
    }
    node.entity = e;
    const r = radarR(e.rssi);
    const angle = sector.start + 8 + stableFraction(e.id) * 74;
    node.g.style.transform = `translate(${RADAR.c}px, ${RADAR.c}px) rotate(${angle}deg) translate(${r}px, 0px)`;
    node.g.style.opacity = e.present ? "1" : "0.35";
    node.g.classList.toggle("selected", state.selected === e.id);
    node.g.setAttribute("aria-label", `${short(e)}: ${e.label_text}, ${Math.round(e.rssi)} dBm`);
    node.g.querySelector(".dot").style.fill = sector.color;
    const half = (e.spread || 0) / 2;
    node.band.setAttribute("x1", radarR(e.rssi + half) - r);
    node.band.setAttribute("x2", radarR(e.rssi - half) - r);
    node.band.style.stroke = sector.color;
  }
  for (const [id, node] of radarNodes) {
    if (!seen.has(id)) { node.g.remove(); radarNodes.delete(id); }
  }
  for (const [key, s] of Object.entries(SECTORS)) sectorLabels[key].textContent = `${s.label} (${counts[key]})`;
}

// ---------- búsqueda: mapa de calor con un receptor móvil ----------
// Visualiza la intensidad de UNA entidad seleccionada sobre los puntos que el
// usuario marca al caminar. No vincula direcciones entre sí: si el dispositivo
// Find My rota su firma (~15 min), hay que volver a seleccionarlo y empezar de nuevo.
const search = { targetId: null, samples: [] };
const SEARCH_GRID = 44;

function searchTargetEntity() {
  if (!state.snap) return null;
  return state.snap.entities.find((e) => e.id === search.targetId) || null;
}

function addSample(nx, ny) {
  const e = searchTargetEntity();
  if (!e || e.rssi === null) return;
  search.samples.push({ x: nx, y: ny, rssi: e.rssi });
  drawSearch();
}

function renderSearchControls() {
  const sel = state.snap.entities.find((e) => e.id === state.selected);
  // Al cambiar de objetivo, los puntos del anterior ya no sirven.
  if (sel && sel.id !== search.targetId) {
    search.targetId = sel.id;
    search.samples = [];
  }
  const e = searchTargetEntity();
  const box = $("#search-target");
  if (!e) {
    box.replaceChildren("Seleccioná una fila de la tabla para elegir qué buscar.");
  } else {
    box.replaceChildren(
      "Buscando: ", h("b", {}, short(e)), ` · ${e.label_text}`,
      e.family ? ` · ${e.family}` : "",
      ` · ahora ${e.rssi === null ? "sin señal" : Math.round(e.rssi) + " dBm"}`,
      ` · ${search.samples.length} puntos`,
    );
  }
}

function drawSearch() {
  const canvas = $("#search");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = rect.width, ht = rect.height;
  ctx.clearRect(0, 0, w, ht);
  const pts = search.samples;
  if (pts.length >= 2) {
    const lo = Math.min(...pts.map((p) => p.rssi)), hi = Math.max(...pts.map((p) => p.rssi));
    const span = hi - lo || 1;
    const cw = w / SEARCH_GRID, ch = ht / SEARCH_GRID;
    for (let gx = 0; gx < SEARCH_GRID; gx++) {
      for (let gy = 0; gy < SEARCH_GRID; gy++) {
        const px = (gx + 0.5) / SEARCH_GRID, py = (gy + 0.5) / SEARCH_GRID;
        let num = 0, den = 0;
        for (const p of pts) {
          const d2 = (px - p.x) ** 2 + (py - p.y) ** 2 + 1e-4;
          const wgt = 1 / (d2 * d2); // distancia inversa al cuadrado: pondera lo cercano
          num += wgt * p.rssi;
          den += wgt;
        }
        const t = Math.max(0, Math.min(1, (num / den - lo) / span)); // 0 débil, 1 fuerte
        ctx.fillStyle = heatColor(t);
        ctx.fillRect(gx * cw, gy * ch, cw + 1, ch + 1);
      }
    }
    // punto marcado más fuerte = candidato "más cerca"
    const peak = pts.reduce((a, b) => (b.rssi > a.rssi ? b : a));
    ctx.strokeStyle = cssVar("--text");
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(peak.x * w, peak.y * ht, 11, 0, 2 * Math.PI);
    ctx.stroke();
  }
  // todos los puntos marcados
  for (const p of pts) {
    ctx.fillStyle = cssVar("--text");
    ctx.beginPath();
    ctx.arc(p.x * w, p.y * ht, 3, 0, 2 * Math.PI);
    ctx.fill();
  }
  renderSearchLegend(pts);
}

// Rampa secuencial de un hue (naranja): claro = señal débil, oscuro = fuerte.
function heatColor(t) {
  const stops = ["#fbe6d5", "#f7c9a6", "#f0a776", "#e8803f", "#c55a1d", "#8a3c11"];
  return stops[Math.round(Math.max(0, Math.min(1, t)) * (stops.length - 1))];
}

function renderSearchLegend(pts) {
  const items = [h("span", {}, "más fuerte / más cerca "), h("span", { class: "dotkey", style: "background:#8a3c11" }),
    h("span", {}, " … "), h("span", { class: "dotkey", style: "background:#fbe6d5" }), h("span", {}, " más débil")];
  if (pts.length) {
    const hi = Math.max(...pts.map((p) => p.rssi)), lo = Math.min(...pts.map((p) => p.rssi));
    items.push(h("span", {}, `rango marcado: ${Math.round(lo)} … ${Math.round(hi)} dBm`));
  }
  if (pts.length < 2) items.push(h("span", {}, "Marcá al menos 2 puntos en distintos lugares."));
  $("#search-legend").replaceChildren(...items);
}

// ---------- plano (ubicación de dispositivos propios) ----------
const PLAN = { margin: 34, px: 520 };
const planNodes = new Map(); // id de entidad -> {g, unc, label}
let planRoomKey = null;
let planScale = 1;

function labColor(labId) {
  const ids = (state.snap.positions || []).map((p) => p.lab_id).filter(Boolean).sort();
  return seriesColor((ids.indexOf(labId) % 5) + 1);
}

function buildPlanBase(room) {
  const svgEl = $("#plan");
  const m = PLAN.margin;
  planScale = PLAN.px / Math.max(room.width, room.height);
  const w = room.width * planScale, ht = room.height * planScale;
  svgEl.setAttribute("viewBox", `0 0 ${w + 2 * m} ${ht + 2 * m}`);
  const defs = svg("defs");
  const clip = svg("clipPath", { id: "plan-clip" });
  clip.append(svg("rect", { x: 0, y: 0, width: w, height: ht }));
  defs.append(clip);
  const base = svg("g", { transform: `translate(${m}, ${m})` });
  for (let x = 1; x < room.width; x++) base.append(svg("line", { x1: x * planScale, y1: 0, x2: x * planScale, y2: ht, class: "plan-grid" }));
  for (let y = 1; y < room.height; y++) base.append(svg("line", { x1: 0, y1: y * planScale, x2: w, y2: y * planScale, class: "plan-grid" }));
  base.append(svg("rect", { x: 0, y: 0, width: w, height: ht, class: "plan-room" }));
  for (let x = 0; x <= room.width; x++) {
    const t = svg("text", { x: x * planScale, y: -8, "text-anchor": "middle" }); t.textContent = `${x} m`; base.append(t);
  }
  for (let y = 1; y <= room.height; y++) {
    const t = svg("text", { x: -6, y: y * planScale + 4, "text-anchor": "end" }); t.textContent = `${y}`; base.append(t);
  }
  const layer = (id, clipped) => svg("g", { id, transform: `translate(${m}, ${m})`, ...(clipped ? { "clip-path": "url(#plan-clip)" } : {}) });
  svgEl.replaceChildren(defs, base, layer("plan-ranges", true), layer("plan-unc", true),
    layer("plan-nodes"), layer("plan-truth"), layer("plan-dots"));
  planNodes.clear();
}

function renderPlan() {
  const room = state.snap.room;
  $("#plan-card").hidden = !room;
  if (!room) return;
  const key = JSON.stringify([room.width, room.height, Object.keys(room.nodes)]);
  if (key !== planRoomKey) { buildPlanBase(room); planRoomKey = key; }
  const S = planScale;
  const status = new Map((state.snap.nodes || []).map((n) => [n.id, n]));

  // receptores
  $("#plan-nodes").replaceChildren(...Object.entries(room.nodes).map(([id, n]) => {
    const st = status.get(id);
    const fresh = st && st.last_seen_s !== null && st.last_seen_s <= 10;
    const g = svg("g", { class: `plan-node ${fresh ? "" : "stale"}`, transform: `translate(${n.x * S}, ${n.y * S})` });
    g.append(svg("rect", { x: -6, y: -6, width: 12, height: 12, rx: 2 }));
    const right = n.x > room.width / 2;
    const label = svg("text", { x: right ? -10 : 10, y: 4, class: "node-label", "text-anchor": right ? "end" : "start" });
    label.textContent = `${id}${n.calibrated ? "" : " (sin calibrar)"}${fresh ? "" : " · sin datos"}`;
    g.append(label);
    return g;
  }));

  // rangos del dispositivo seleccionado (uno por receptor)
  const selected = (state.snap.positions || []).find((p) => p.id === state.selected);
  $("#plan-ranges").replaceChildren(...(selected ? selected.ranges.map((r) => {
    const n = room.nodes[r.node];
    return svg("circle", { cx: n.x * S, cy: n.y * S, r: r.d * S, class: "plan-range", style: `stroke: ${labColor(selected.lab_id)}` });
  }) : []));

  // posiciones estimadas
  const seen = new Set();
  for (const p of state.snap.positions || []) {
    if (p.x === null) continue;
    seen.add(p.id);
    let node = planNodes.get(p.id);
    if (!node) {
      const g = svg("g", { class: "plan-pos" });
      const unc = svg("circle", { class: "unc plan-unc-circle" });
      const label = svg("text", { y: -10, class: "pos-label" });
      g.append(svg("circle", { class: "dot", r: 6 }), label);
      $("#plan-unc").append(unc);
      g.addEventListener("click", () => { state.selected = p.id; history.replaceState(null, "", `#e=${p.id}`); render(); });
      node = { g, unc, label };
      planNodes.set(p.id, node);
      $("#plan-dots").append(g);
    }
    const color = labColor(p.lab_id);
    node.g.style.transform = `translate(${p.x * S}px, ${p.y * S}px)`;
    node.unc.style.cx = `${p.x * S}px`;
    node.unc.style.cy = `${p.y * S}px`;
    node.unc.style.r = `${Math.max(6, p.radius * S)}px`;
    const right = p.x > room.width * 0.6;
    node.label.setAttribute("x", right ? -10 : 10);
    node.label.setAttribute("text-anchor", right ? "end" : "start");
    node.unc.style.fill = color;
    node.unc.style.stroke = color;
    node.g.querySelector(".dot").style.fill = color;
    node.label.textContent = `${p.lab_id} ±${p.radius.toFixed(1)} m`;
  }
  for (const [id, node] of planNodes) if (!seen.has(id)) { node.g.remove(); node.unc.remove(); planNodes.delete(id); }

  // verdad (solo en la demo con simulador)
  const truth = state.snap.truth || {};
  $("#plan-truth").replaceChildren(...Object.entries(truth).map(([id, [x, y]]) => {
    const g = svg("g", { transform: `translate(${x * S}, ${y * S})` });
    g.append(svg("circle", { r: 8, class: "plan-truth" }));
    const ent = state.snap.entities.find((e) => e.id === id);
    const t = svg("text", { x: -10, y: 20, "text-anchor": "end" });
    t.textContent = `real ${ent && ent.lab_id ? ent.lab_id : ""} (simulada)`;
    g.append(t);
    return g;
  }));

  const foreign = state.snap.entities.filter((e) => e.present && !e.lab_id).length;
  const lines = (state.snap.positions || []).map((p) =>
    h("div", {}, h("b", {}, p.lab_id), ": ", p.status,
      p.x !== null ? ` · (${p.x}, ${p.y}) m ±${p.radius} m · receptores: ${p.nodes_used.join(", ")}` : ""));
  if (!lines.length) lines.push(h("div", {}, "Ninguna entidad con LAB-ID presente. Asigná un LAB-ID a un dispositivo propio desde el panel de detalle."));
  lines.push(h("div", {}, `${foreign} entidades ajenas presentes: no se ubican (privacidad).`));
  $("#plan-status").replaceChildren(...lines);
}

async function calibrate(entityId, nodeId, distance, out) {
  out.textContent = "calibrando…";
  try {
    const res = await fetch("/api/calibrate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_id: entityId, node_id: nodeId, distance_m: distance }),
    });
    const data = await res.json();
    out.textContent = res.ok ? `${data.node}: ${data.rssi} dBm a ${data.distance_m} m → ref ${data.ref_dbm} dBm a 1 m` : (data.detail || "error");
  } catch (err) {
    out.textContent = "No se pudo calibrar.";
  }
}

// ---------- gráfico ----------
const PAD = { l: 44, r: 72, t: 10, b: 22 };

function chartGeometry(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
  }
  const now = state.snap ? toSec(state.snap.t) : Date.now() / 1000;
  let lo = -100, hi = -30;
  for (const pts of state.series.values()) for (const [, v] of pts) { lo = Math.min(lo, v - 5); hi = Math.max(hi, v + 5); }
  lo = Math.floor(lo / 10) * 10; hi = Math.ceil(hi / 10) * 10;
  const w = rect.width, ht = rect.height;
  return {
    dpr, w, ht, now, lo, hi,
    x: (t) => PAD.l + ((t - (now - WINDOW_S)) / WINDOW_S) * (w - PAD.l - PAD.r),
    y: (v) => PAD.t + ((hi - v) / (hi - lo)) * (ht - PAD.t - PAD.b),
    tAt: (px) => now - WINDOW_S + ((px - PAD.l) / (w - PAD.l - PAD.r)) * WINDOW_S,
  };
}

function drawChart() {
  const canvas = $("#chart");
  const g = chartGeometry(canvas);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
  ctx.clearRect(0, 0, g.w, g.ht);
  ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";

  // grilla horizontal y eje Y
  ctx.lineWidth = 1;
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let v = g.lo; v <= g.hi; v += 10) {
    ctx.strokeStyle = cssVar("--grid");
    ctx.beginPath(); ctx.moveTo(PAD.l, Math.round(g.y(v)) + 0.5); ctx.lineTo(g.w - PAD.r, Math.round(g.y(v)) + 0.5); ctx.stroke();
    ctx.fillStyle = cssVar("--muted");
    ctx.fillText(`${v}`, PAD.l - 6, g.y(v));
  }
  // umbrales de categoría (referencia, no distancia)
  ctx.strokeStyle = cssVar("--axis");
  ctx.textAlign = "left";
  for (const [v, above, below] of [[STRONG, "fuerte", null], [MEDIUM, "media", "débil"]]) {
    if (v < g.lo || v > g.hi) continue;
    ctx.beginPath(); ctx.moveTo(PAD.l, Math.round(g.y(v)) + 0.5); ctx.lineTo(g.w - PAD.r, Math.round(g.y(v)) + 0.5); ctx.stroke();
    ctx.fillStyle = cssVar("--muted");
    ctx.textBaseline = "bottom"; ctx.fillText(above, PAD.l + 4, g.y(v) - 2);
    if (below) { ctx.textBaseline = "top"; ctx.fillText(below, PAD.l + 4, g.y(v) + 2); }
  }
  // eje X
  ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillStyle = cssVar("--muted");
  for (let m = 0; m <= WINDOW_S / 60; m++) {
    const t = g.now - m * 60;
    ctx.fillText(m === 0 ? "ahora" : `-${m} min`, g.x(t), g.ht - PAD.b + 6);
  }
  ctx.strokeStyle = cssVar("--axis");
  ctx.beginPath(); ctx.moveTo(PAD.l, g.ht - PAD.b + 0.5); ctx.lineTo(g.w - PAD.r, g.ht - PAD.b + 0.5); ctx.stroke();

  // series
  const ends = [];
  ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.lineCap = "round";
  for (const [id, slot] of state.plotted) {
    const pts = (state.series.get(id) || []).filter(([t]) => t >= g.now - WINDOW_S);
    if (!pts.length) continue;
    ctx.strokeStyle = seriesColor(slot);
    ctx.beginPath();
    pts.forEach(([t, v], i) => {
      const gap = i > 0 && t - pts[i - 1][0] > GAP_BREAK_S;
      if (i === 0 || gap) ctx.moveTo(g.x(t), g.y(v)); else ctx.lineTo(g.x(t), g.y(v));
    });
    ctx.stroke();
    const [lt, lv] = pts[pts.length - 1];
    ends.push({ id, slot, x: g.x(lt), y: g.y(lv) });
  }
  // etiquetas directas (≤ 4 series y sin colisiones; si no, alcanza la leyenda)
  const ys = ends.map((e) => e.y).sort((a, b) => a - b);
  const collide = ys.some((y, i) => i > 0 && y - ys[i - 1] < 13);
  if (ends.length <= 4 && !collide) {
    ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillStyle = cssVar("--text-2");
    const entities = new Map(state.snap.entities.map((e) => [e.id, e]));
    for (const end of ends) {
      const e = entities.get(end.id);
      ctx.fillText(e ? short(e) : end.id.slice(0, 6), g.w - PAD.r + 8, end.y);
    }
  }

  // crosshair
  if (state.hoverX !== null && state.hoverX >= PAD.l && state.hoverX <= g.w - PAD.r) {
    ctx.strokeStyle = cssVar("--text-2"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(Math.round(state.hoverX) + 0.5, PAD.t); ctx.lineTo(Math.round(state.hoverX) + 0.5, g.ht - PAD.b); ctx.stroke();
  }
  renderLegend();
  renderTooltip(g);
}

function renderLegend() {
  const entities = state.snap ? new Map(state.snap.entities.map((e) => [e.id, e])) : new Map();
  const items = [...state.plotted].map(([id, slot]) => {
    const e = entities.get(id);
    return h("span", {}, h("span", { class: "key", style: `background:${seriesColor(slot)}` }),
      e ? `${short(e)} · ${e.label_text}` : id.slice(0, 6));
  });
  $("#legend").replaceChildren(...(items.length ? items : [h("span", {}, "Sin series seleccionadas.")]));
}

function renderTooltip(g) {
  const tip = $("#tooltip");
  if (state.hoverX === null || !state.plotted.size) { tip.hidden = true; return; }
  const t = g.tAt(state.hoverX);
  const entities = new Map(state.snap.entities.map((e) => [e.id, e]));
  const rows = [];
  for (const [id, slot] of state.plotted) {
    const pts = state.series.get(id) || [];
    let best = null;
    for (const p of pts) if (Math.abs(p[0] - t) <= 3 && (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t))) best = p;
    const e = entities.get(id);
    rows.push(h("div", { class: "row" }, h("span", { class: "key", style: `background:${seriesColor(slot)}` }),
      h("span", { class: "val" }, best ? `${best[1].toFixed(1)} dBm` : "—"), e ? short(e) : id.slice(0, 6)));
  }
  const secs = Math.round(g.now - t);
  tip.replaceChildren(h("div", { class: "when" }, secs <= 0 ? "ahora" : `hace ${secs} s`), ...rows);
  tip.hidden = false;
  const left = state.hoverX + 12 + tip.offsetWidth > g.w ? state.hoverX - 12 - tip.offsetWidth : state.hoverX + 12;
  tip.style.left = `${left}px`;
  tip.style.top = `${PAD.t}px`;
}

function initSearch() {
  const canvas = $("#search");
  canvas.addEventListener("pointerdown", (ev) => {
    const r = canvas.getBoundingClientRect();
    addSample((ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height);
  });
  $("#search-undo").addEventListener("click", () => { search.samples.pop(); drawSearch(); });
  $("#search-clear").addEventListener("click", () => { search.samples = []; drawSearch(); });
  drawSearch();
}

// ---------- eventos de UI ----------
function init() {
  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.addEventListener("click", () => {
      if (state.sortKey === th.dataset.sort) state.sortAsc = !state.sortAsc;
      else { state.sortKey = th.dataset.sort; state.sortAsc = false; }
      render();
    });
  }
  for (const id of ["#f-text", "#f-label", "#f-present"]) $(id).addEventListener("input", render);
  $("#f-rssi").addEventListener("input", () => {
    const v = Number($("#f-rssi").value);
    $("#f-rssi-out").textContent = v <= -110 ? "sin filtro" : `≥ ${v} dBm`;
    render();
  });
  const canvas = $("#chart");
  canvas.addEventListener("pointermove", (ev) => {
    state.hoverX = ev.clientX - canvas.getBoundingClientRect().left;
    drawChart();
  });
  canvas.addEventListener("pointerleave", () => { state.hoverX = null; drawChart(); });
  window.addEventListener("resize", () => { drawChart(); drawSearch(); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  initRadar();
  initSearch();
  const fromHash = location.hash.match(/^#e=([0-9a-f]+)$/);
  if (fromHash) state.selected = fromHash[1];
  loadMeta();
  connect();
}

init();
