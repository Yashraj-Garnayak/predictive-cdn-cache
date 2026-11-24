// Live dashboard: controls -> REST, updates <- WebSocket /ws/live (a "state" message, then one "hour" message per hour).
const POLICIES = ["Hybrid", "Predictive", "LFU", "LRU"];
const COLOR = { Hybrid: "#0A84FF", LFU: "#BF5AF2", Predictive: "#FF9F0A", LRU: "#8E8E93" };
const DASH = { Hybrid: null, Predictive: "7 4", LFU: "2 4", LRU: "12 5" };   // not colour alone
const TRENDS = { rising: "↑ rising fast", steady: "→ steady", fading: "↓ fading" };
const STATUS = { idle: "Ready", warming: "Warming up", playing: "Playing", paused: "Paused",
                 finished: "Finished", error: "Error", offline: "Reconnecting" };
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let status = "idle", history = [], last = null, prev = null, total = 0, config = null;

// ---------- REST ----------
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail
    : (data.detail || []).map(d => `${d.loc?.at(-1)}: ${d.msg}`).join("; ") || res.statusText);
  return data;
}
function showError(msg) { const a = $("alert"); a.textContent = msg || ""; a.hidden = !msg; }

async function loadRegions() {
  try {
    const { source, regions } = await api("/api/regions");
    $("source").textContent = source === "database" ? "PostgreSQL · requests_hourly" : "Local CSV";
    $("region").innerHTML = regions.map(r => `<option>${esc(r)}</option>`).join("");
    $("region").disabled = false;
    if (config) $("region").value = config.region;
    showError("");
  } catch (e) {
    $("source").textContent = "Data source unavailable";
    showError(`Can't load regions: ${e.message}`);
    setTimeout(loadRegions, 5000);
  }
}

async function control(action) {
  const btn = $(action);
  btn.disabled = true;
  try {
    showError("");
    if (action === "start") {
      const capacity = Number($("capacity").value);
      if (!(capacity >= 10 && capacity <= 5000)) throw new Error("Capacity must be between 10 and 5000 videos.");
      btn.classList.add("busy");
      await api("/api/simulate/start", { region: $("region").value, capacity, speed: Number($("speed").value) });
    } else {
      await api(`/api/simulate/${action}`, {});
    }
  } catch (e) { showError(e.message); }
  finally { btn.classList.remove("busy"); renderControls(); }
}
for (const a of ["start", "pause", "reset"]) $(a).addEventListener("click", () => control(a));
$("speed").addEventListener("change", () => { if (status === "playing") control("start"); });  // live speed change

// ---------- WebSocket ----------
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/live`);
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === "state") applyState(msg); else onHour(msg);
  };
  ws.onclose = () => { setStatus("offline"); setTimeout(connect, 1500); };
}

function applyState(s) {
  config = s.config; total = s.total; history = s.history;
  if (s.last?.hour !== last?.hour) prev = null;
  last = s.last;
  if (config) {
    $("region").value = config.region; $("capacity").value = config.capacity;
    $("speed").value = String(config.speed);
  }
  setStatus(s.status);
  showError(s.status === "error" ? s.message : "");
  renderAll();
}

function onHour(msg) {
  prev = last; last = msg; total = msg.total;
  history.push({ hour: msg.hour, hit_rate: msg.hit_rate });
  renderAll();
}

function setStatus(s) {
  status = s;
  const pill = $("status");
  pill.className = `pill ${s}`; pill.textContent = STATUS[s] || s;
  renderControls();
}

function renderControls() {
  const running = status === "playing" || status === "warming";
  $("start").disabled = running || status === "offline";
  $("start").querySelector("span").textContent = status === "warming" ? "Warming up…" : status === "paused" ? "Resume" : "Start";
  $("start").classList.toggle("busy", status === "warming");
  $("pause").disabled = !running;
  $("reset").disabled = status === "idle" || status === "offline";
}

// ---------- rendering ----------
function renderAll() {
  renderProgress(); renderCards(); drawChart(); renderTable();
  Bubbles.update(last ? last.bubbles : []);
}

function renderProgress() {
  const done = history.length;
  $("progress-fill").style.transform = `scaleX(${total ? done / total : 0})`;
  $("progress-label").textContent =
    status === "warming" ? "Replaying warm-up hours and training the model…"
    : !last ? (status === "idle" ? "Pick a region and press Start. The first half of the hours trains the model; the replay shows the rest."
                                 : "Waiting for the first hour…")
    : `${config.region} · hour ${last.hour} · test hour ${done} of ${total}`;
}

function delta(id, now, before, digits, higherIsBetter = true, unit = "") {
  const el = $(id);
  if (before == null) { el.textContent = ""; el.className = "delta"; return; }
  const d = now - before, text = (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(digits);
  const flat = Number(Math.abs(d).toFixed(digits)) === 0;
  el.textContent = flat ? "No change vs last hour" : `${text}${unit} vs last hour`;
  el.className = "delta " + (flat ? "flat" : (d > 0) === higherIsBetter ? "good" : "bad");
}

function renderCards() {
  const r = last, p = prev;
  $("m-precision").textContent = r ? Math.round(r.precision * 10) : "–";
  $("m-mae").textContent = r ? r.mae.toFixed(2) : "–";
  $("m-lead").textContent = r ? (r.hybrid_lead >= 0 ? "+" : "") + r.hybrid_lead.toFixed(2) : "–";
  $("m-hybrid").textContent = r ? r.hit_rate.Hybrid.toFixed(1) : "–";
  delta("d-precision", r?.precision * 10, p && p.precision * 10, 0);
  delta("d-mae", r?.mae, p?.mae, 2, false);
  delta("d-lead", r?.hybrid_lead, p?.hybrid_lead, 2, true, " pts");
  delta("d-hybrid", r?.hit_rate.Hybrid, p?.hit_rate.Hybrid, 2, true, " pts");
}

// ---------- chart ----------
const legend = $("legend");
legend.innerHTML = POLICIES.map(p => `<li><svg viewBox="0 0 22 8" aria-hidden="true"><line x1="1" y1="4" x2="21" y2="4"
  stroke="${COLOR[p]}" stroke-width="${p === "Hybrid" ? 3 : 2.25}" stroke-linecap="round"${DASH[p] ? ` stroke-dasharray="${DASH[p]}"` : ""}/></svg>
  ${p} <b data-p="${p}">–</b></li>`).join("");

const chartEl = $("chart");
let hoverHour = null;
function drawChart() {
  const W = chartEl.clientWidth, H = chartEl.clientHeight, m = { t: 8, r: 12, b: 26, l: 40 };
  for (const p of POLICIES) legend.querySelector(`[data-p="${p}"]`).textContent = last ? last.hit_rate[p].toFixed(1) + "%" : "–";
  chartEl.setAttribute("aria-label", last
    ? `Line chart of running hit rate per policy. Latest, hour ${last.hour}: ` + POLICIES.map(p => `${p} ${last.hit_rate[p].toFixed(1)}%`).join(", ")
    : "Line chart of hit rate per policy. No data yet.");
  if (!history.length) { chartEl.innerHTML = '<div class="empty">The chart fills in as hours are simulated.</div>'; return; }

  const x = d3.scaleLinear().domain(d3.extent(history, d => d.hour)).range([m.l, W - m.r]);
  if (history.length === 1) x.domain([history[0].hour - 1, history[0].hour + 1]);
  const vals = history.flatMap(d => POLICIES.map(p => d.hit_rate[p]));
  const y = d3.scaleLinear().domain([Math.max(0, d3.min(vals) - 2), Math.min(100, d3.max(vals) + 2)]).nice().range([H - m.b, m.t]);
  const svg = d3.select(chartEl).selectAll("svg").data([0]).join("svg");
  chartEl.querySelector(".empty")?.remove();
  svg.selectAll("g.grid").data([0]).join("g").attr("class", "grid")
    .attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickSize(-(W - m.l - m.r)).tickFormat(""));
  svg.selectAll("g.y").data([0]).join("g").attr("class", "axis y")
    .attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(d => d + "%"));
  svg.selectAll("g.x").data([0]).join("g").attr("class", "axis x")
    .attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.max(2, Math.floor(W / 90))).tickFormat(d => "h" + d));
  const line = p => d3.line().x(d => x(d.hour)).y(d => y(d.hit_rate[p])).curve(d3.curveMonotoneX)(history);
  svg.selectAll("path.line").data([...POLICIES].reverse(), d => d).join("path")
    .attr("class", p => "line " + p).attr("stroke", p => COLOR[p]).attr("stroke-dasharray", p => DASH[p]).attr("d", line);
  // hover / tap: vertical rule + values at the nearest hour
  const near = hoverHour == null ? null : history.reduce((a, b) => Math.abs(b.hour - hoverHour) < Math.abs(a.hour - hoverHour) ? b : a);
  svg.selectAll("line.rule").data(near ? [near] : []).join("line").attr("class", "rule")
    .attr("x1", d => x(d.hour)).attr("x2", d => x(d.hour)).attr("y1", m.t).attr("y2", H - m.b);
  let tipEl = chartEl.querySelector(".chart-tip");
  if (!near) { tipEl?.remove(); }
  else {
    tipEl ??= chartEl.appendChild(Object.assign(document.createElement("div"), { className: "chart-tip" }));
    tipEl.innerHTML = `<div><b>Hour ${near.hour}</b></div>` + POLICIES.map(p =>
      `<div><span style="color:${COLOR[p]}">${p}</span><b>${near.hit_rate[p].toFixed(2)}%</b></div>`).join("");
    const left = x(near.hour) + 12;
    tipEl.style.left = (left + tipEl.offsetWidth > W ? x(near.hour) - tipEl.offsetWidth - 12 : left) + "px";
  }
  svg.on("pointermove", e => { hoverHour = x.invert(d3.pointer(e)[0]); drawChart(); })
     .on("pointerleave", () => { hoverHour = null; drawChart(); });
}
new ResizeObserver(() => drawChart()).observe(chartEl);

// ---------- table ----------
const TICK = '<svg class="mark yes" viewBox="0 0 16 16" role="img" aria-label="in both lists"><path d="M3 8.5l3 3 7-7"/></svg>';
function cell(title, count, match, trend, tags, digits) {
  if (!title) return "<td></td>";
  const chips = (trend ? `<span class="chip ${trend}">${TRENDS[trend]}</span>` : "")
              + (tags || []).map(t => `<span class="chip">${esc(t)}</span>`).join("");
  return `<td class="${match ? "match" : ""}"><div class="cell">${match ? TICK : '<span class="mark"></span>'}`
       + `<span class="title">${esc(title)}</span><span class="count">${Number(count).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}</span>`
       + (chips ? `<div class="chips">${chips}</div>` : "") + "</div></td>";
}
function renderTable() {
  const body = $("top10").tBodies[0];
  $("table-sub").textContent = last ? `Hour ${last.hour} · green tick = the video is in both lists` : "Green tick = the video is in both lists";
  if (!last) { body.innerHTML = '<tr><td colspan="3" class="empty-row">No hour simulated yet.</td></tr>'; return; }
  body.innerHTML = last.top10.map(r => `<tr><td>${r.rank}</td>`
    + cell(r.pred_title, r.pred_count, r.pred_match, r.pred_trend, r.pred_tags, 1)
    + cell(r.act_title, r.act_count, r.act_match, r.act_trend, r.act_tags, 0) + "</tr>").join("");
}

// ---------- "How it works" overlay ----------
// The explainer page runs in a frame inside a <dialog>: no reload, and the live simulation keeps running underneath.
// The frame is only loaded on first open, so the dashboard itself stays light.
const hiw = $("hiw"), frame = $("hiw-frame");
let hiwOpener = null;
function openHiw(step, opener) {
  hiwOpener = opener;
  if (!hiw.open) hiw.showModal();                                     // open first: a closed dialog can't scroll
  if (frame.contentWindow?.HIW) frame.contentWindow.HIW.go(step);     // already loaded: jump to the step
  else frame.src = `how-it-works.html?embed#${step}`;                // first open: load it at that step
  hideHint();
}
function closeHiw() { if (hiw.open) hiw.close(); }
hiw.addEventListener("close", () => hiwOpener?.focus());
hiw.addEventListener("click", e => { if (e.target === hiw) closeHiw(); });   // click on the dimmed edge
$("hiw-close").addEventListener("click", closeHiw);
window.addEventListener("message", e => { if (e.origin === location.origin && e.data === "hiw:close") closeHiw(); });
document.querySelectorAll("[data-hiw-step]").forEach(el => el.addEventListener("click", e => {
  e.preventDefault(); openHiw(el.dataset.hiwStep, el);
}));

// one-time hint for first visits, remembered in this browser (storage may be blocked: then it just shows)
const HINT_KEY = "pcache.hiw-hint-seen";
function hideHint() {
  $("hiw-hint").hidden = true;
  try { localStorage.setItem(HINT_KEY, "1"); } catch { /* private mode: fine */ }
}
try { if (!localStorage.getItem(HINT_KEY)) $("hiw-hint").hidden = false; } catch { $("hiw-hint").hidden = false; }
$("hiw-hint-close").addEventListener("click", hideHint);

renderControls();
loadRegions();
connect();
