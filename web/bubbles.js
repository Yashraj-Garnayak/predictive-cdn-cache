// Liquid Glass "Trending now" bubbles: D3 physics, push away from the cursor, grab and throw.
// app.js calls Bubbles.update(data) once per simulated hour; bubbles glide between hours.
window.Bubbles = (() => {
const stage = document.getElementById("stage"), tip = document.getElementById("tip");
const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let W = stage.clientWidth, H = stage.clientHeight, nodes = [], mouse = null, drag = null;
const fmt = d3.format(","), fmt1 = d3.format(",.1f");
const ARROWS = { rising: "↑", steady: "→", fading: "↓" };                 
const TRENDS = { rising: "rising fast", steady: "steady", fading: "fading" }; // same as api/content.py TREND_LABELS

// ---------- physics ----------
// Speeds are in pixels per simulation tick (about 1/60 s).
const MAX_SPEED = 40;     // fastest a thrown bubble can fly
const GLIDE_SPEED = 2.5;  // faster than this a bubble glides (little friction); slower, it settles quickly
const BOUNCE = 0.82;      // share of speed kept after hitting a wall or another bubble
function friction() {
  for (const n of nodes) {
    if (n.fx != null) continue;          // being held
    const k = Math.hypot(n.vx, n.vy) > GLIDE_SPEED ? 0.995 : 0.9;
    n.vx *= k; n.vy *= k;
  }
}
function impacts() {     // billiard-style bounces whenever a fast bubble touches another one
  for (const a of nodes) {
    if (Math.hypot(a.vx, a.vy) < GLIDE_SPEED) continue;
    for (const b of nodes) {
      if (a === b) continue;
      // look one step ahead, so a fast bubble cannot skip through a small one
      const dx = b.x + b.vx - a.x - a.vx, dy = b.y + b.vy - a.y - a.vy, d = Math.hypot(dx, dy) || 1;
      if (d > a.r + b.r + 4) continue;
      const nx = dx / d, ny = dy / d, closing = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
      if (closing <= 0) continue;                         // already moving apart
      // heavier = bigger (at least 1, since a new bubble starts at size 0); a held bubble acts as a wall
      const ma = Math.max(1, a.r * a.r), mb = b.fx != null ? 1e9 : Math.max(1, b.r * b.r);
      const j = (1 + BOUNCE) * closing / (1 / ma + 1 / mb);
      a.vx -= j / ma * nx; a.vy -= j / ma * ny;
      b.vx += j / mb * nx; b.vy += j / mb * ny;
    }
  }
}
function wander() {                      // gentle floating
  if (calm) return;
  const t = performance.now() / 1000;
  for (const n of nodes) {
    n.vx += Math.cos(t * 0.5 + n.phase) * 0.018;
    n.vy += Math.sin(t * 0.4 + n.phase * 1.7) * 0.018;
  }
}
function repel() {                       // push away from the mouse cursor (not while dragging)
  if (!mouse || drag) return;
  for (const n of nodes) {
    const dx = n.x - mouse.x, dy = n.y - mouse.y, d = Math.hypot(dx, dy) || 1, reach = n.r + 80;
    if (d < n.r) continue;               // the bubble under the cursor holds still, so it is easy to grab
    if (d < reach) { const f = (1 - d / reach) * 1.6; n.vx += dx / d * f; n.vy += dy / d * f; }
  }
}
const collide = d3.forceCollide(d => d.r + 4).strength(0.85).iterations(3);
const sim = d3.forceSimulation([])
  .alpha(1).alphaDecay(0).velocityDecay(0.02)        // never cools down; friction() does the slowing
  .force("x", d3.forceX(() => W / 2).strength(0.004))
  .force("y", d3.forceY(() => H / 2).strength(0.008))
  .force("collide", collide).force("wander", wander).force("repel", repel).force("impacts", impacts).force("friction", friction)
  .on("tick", tick);

let lastT = performance.now();
function tick() {
  const now = performance.now(), ease = 1 - Math.exp(-(now - lastT) / 180);  // time-based, so speed is
  lastT = now;                                                                 // the same at any frame rate
  let resized = false;
  for (const n of nodes) {
    const dr = n.target - n.r;           // ease radius toward its new size
    if (Math.abs(dr) > 0.1) { n.r += dr * ease; resized = true; }
    const v = Math.hypot(n.vx, n.vy);
    if (v > MAX_SPEED) { n.vx *= MAX_SPEED / v; n.vy *= MAX_SPEED / v; }
    // bounce off the edges: put the bubble back inside and reverse its direction
    if (n.x < n.r) { n.x = n.r; if (n.vx < 0) n.vx *= -BOUNCE; }
    if (n.x > W - n.r) { n.x = W - n.r; if (n.vx > 0) n.vx *= -BOUNCE; }
    if (n.y < n.r) { n.y = n.r; if (n.vy < 0) n.vy *= -BOUNCE; }
    if (n.y > H - n.r) { n.y = H - n.r; if (n.vy > 0) n.vy *= -BOUNCE; }
  }
  if (resized) collide.radius(d => d.r + 4);
  for (const n of nodes) {
    const s = n.el.style, d = 2 * n.r;
    s.width = s.height = d + "px";
    s.transform = `translate(${n.x - n.r}px, ${n.y - n.r}px)`;
    s.opacity = Math.min(1, n.r / (0.6 * n.target || 1));
    if (Math.abs(n.fontFor - d) > 3) layoutLabel(n, d);
  }
}

// ---------- drawing ----------
function layoutLabel(n, d) {
  n.fontFor = d;
  const fs = Math.max(9, Math.min(17, d / 7.5)), chars = Math.max(6, Math.round(d / fs * 1.6));
  const t = n.datum.label.length > chars ? n.datum.label.slice(0, chars - 1).trimEnd() + "…" : n.datum.label;
  n.labelT.textContent = d < 34 ? "" : t;
  n.labelT.style.fontSize = fs + "px";
  n.labelC.style.fontSize = Math.max(8, fs * 0.66) + "px";
  n.labelC.style.display = d < 84 || !n.datum.type ? "none" : "";   // type chip only where it fits
  n.labelN.style.fontSize = Math.max(8, fs * 0.78) + "px";
  n.labelN.style.display = d < 70 ? "none" : "";
  n.labelG.style.fontSize = Math.max(8, fs * 0.7) + "px";
  n.labelG.style.display = d < 110 || !n.datum.trend ? "none" : "";   // words only on big bubbles
}
function makeNode(datum) {
  const el = document.createElement("div");
  el.className = "bubble";
  el.innerHTML = '<div class="glow"></div><div class="sphere"><div class="tint g"></div><div class="tint p"></div>'
               + '<div class="caustic"></div><div class="shine"></div><div class="spec"></div><div class="rim"></div><div class="label"><div class="t"></div><div class="c"></div><div class="n"></div>'
               + '<div class="g"></div></div></div>';
  stage.appendChild(el);
  const side = Math.random() * 2 * Math.PI;           // float in from just inside a random edge
  const n = { id: datum.id, el, r: 0, target: 0, phase: Math.random() * 6.28, fontFor: -99,
              x: W / 2 + Math.cos(side) * W * 0.35, y: H / 2 + Math.sin(side) * H * 0.35, vx: 0, vy: 0,
              labelT: el.querySelector(".t"), labelC: el.querySelector(".c"), labelN: el.querySelector(".n"), labelG: el.querySelector(".label .g") };
  el.querySelector(".glow").style.animationDelay = -Math.random() * 5 + "s";  // glows breathe out of step
  el.addEventListener("mouseenter", () => { if (!drag) showTip(n); });
  el.addEventListener("mouseleave", () => tip.classList.remove("on"));
  el.addEventListener("pointerdown", e => grab(e, n));
  return n;
}
function radii(data) {                   // area ~ requests; bubbles fill about a third of the stage
  const total = d3.sum(data, d => d.actual) || 1, k = Math.sqrt(0.32 * W * H / (Math.PI * total));
  const max = Math.min(W, H) * 0.24;
  return d => Math.max(22, Math.min(max, k * Math.sqrt(d.actual)));
}
function update(data) {
  document.getElementById("empty").style.opacity = data.length ? 0 : 1;
  const r = radii(data), byId = new Map(nodes.map(n => [n.id, n])), seen = new Set();
  for (const d of data) {
    const n = byId.get(d.id) || makeNode(d);
    if (!byId.has(d.id)) nodes.push(n);
    n.datum = d; n.target = r(d); n.fontFor = -99; seen.add(d.id);
    n.el.classList.toggle("hit", d.hit); n.el.classList.toggle("miss", !d.hit);
    n.labelC.textContent = d.type || "";
    n.labelN.textContent = fmt(d.actual) + (d.trend ? " " + ARROWS[d.trend] : "");
    n.labelG.textContent = d.trend ? TRENDS[d.trend] : "";
    n.labelG.className = "g " + (d.trend || "");
  }
  for (const n of nodes) if (!seen.has(n.id)) {   // dropped out of the top list: fade away, then remove
    n.el.classList.add("leaving"); setTimeout(() => n.el.remove(), 700);
    if (tipNode === n) tip.classList.remove("on");
  }
  if (drag && !seen.has(drag.n.id)) release();     // the held bubble left the top list
  nodes = nodes.filter(n => seen.has(n.id));
  sim.nodes(nodes);
  if (tipNode && tip.classList.contains("on")) showTip(tipNode);
}

// ---------- tooltip ----------
let tipNode = null;
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function showTip(n) {
  tipNode = n; const d = n.datum;
  const row = (k, v) => v ? `<div class="row">${k} <b>${esc(v)}</b></div>` : "";   // no value (no titles row) -> no row
  tip.innerHTML = `<div class="tt">${esc(d.label)}</div>`
    + (d.title !== d.label ? `<div class="tn">${esc(d.title)}</div>` : "")
    + row("Content type", d.type) + row("Size", d.size)
    + row("Actual requests", fmt(d.actual)) + row("Predicted requests", fmt1(d.predicted)) + row("Region", d.region)
    + `<div class="chips"><span class="chip ${d.hit ? "hit" : "miss"}">${d.hit ? "Model predicted it" : "Model missed it"}</span>`
    + (d.trend ? `<span class="chip ${d.trend}">${ARROWS[d.trend]} ${TRENDS[d.trend]}</span>` : "")
    + `</div>`;
  tip.classList.add("on");
}
function pointAt(e) { const b = stage.getBoundingClientRect(); return { x: e.clientX - b.left, y: e.clientY - b.top, t: performance.now() }; }
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// ---------- grab and throw ----------
// While held, the bubble follows the pointer (fx/fy pin it in the simulation) and shoves others aside.
// On release, the pointer's speed over the last ~100 ms becomes the bubble's speed: a flick throws it.
function grab(e, n) {
  if (e.button !== 0) return;
  e.preventDefault();
  const p = pointAt(e);
  drag = { n, dx: n.x - p.x, dy: n.y - p.y, trail: [p] };
  n.fx = n.x; n.fy = n.y;
  n.el.classList.add("dragging"); stage.classList.add("grabbing");
  tip.classList.remove("on");
  stage.setPointerCapture(e.pointerId);
}
function release() {
  if (!drag) return;
  const { n, trail } = drag, a = trail[0], b = trail[trail.length - 1];
  const stillMoving = performance.now() - b.t < 80;          // paused before letting go = drop, not throw
  const perTick = stillMoving ? 16.7 / Math.max(16, b.t - a.t) : 0;   // px per ms -> px per tick
  n.fx = n.fy = null;
  n.vx = (b.x - a.x) * perTick; n.vy = (b.y - a.y) * perTick;
  n.el.classList.remove("dragging"); stage.classList.remove("grabbing");
  drag = null;
}
stage.addEventListener("pointermove", e => {
  const p = pointAt(e);
  mouse = p;
  if (drag) {
    const n = drag.n;
    n.fx = clamp(p.x + drag.dx, n.r, W - n.r); n.fy = clamp(p.y + drag.dy, n.r, H - n.r);
    drag.trail.push(p);
    while (drag.trail.length > 2 && drag.trail[0].t < p.t - 100) drag.trail.shift();
    return;
  }
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = Math.min(W - tw - 8, p.x + 14) + "px";
  tip.style.top = (p.y + th + 20 > H ? p.y - th - 14 : p.y + 16) + "px";
});
stage.addEventListener("pointerup", release);
stage.addEventListener("pointercancel", release);
stage.addEventListener("pointerleave", () => { if (!drag) { mouse = null; tip.classList.remove("on"); } });

new ResizeObserver(() => {
  W = stage.clientWidth; H = stage.clientHeight;
  if (nodes.length) { const r = radii(nodes.map(n => n.datum)); nodes.forEach(n => { n.target = r(n.datum); }); }
}).observe(stage);
return { update };
})();
