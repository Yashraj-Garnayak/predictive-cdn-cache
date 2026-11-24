// "How it works": play each step's animation when it scrolls into view; dots + Next as an alternative to scrolling.
// Without JS (or with reduced motion) every step simply shows its finished state.
document.documentElement.classList.replace("no-js", "js");
// Inside the dashboard's overlay (?embed): no own header; Escape and "Dashboard" links close the overlay instead.
const embedded = new URLSearchParams(location.search).has("embed") && window.parent !== window;
if (embedded) document.documentElement.classList.add("embed");
const closeOverlay = () => window.parent.postMessage("hiw:close", location.origin);
const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const steps = [...document.querySelectorAll(".step")];
const dots = [...document.querySelectorAll(".dots a")];
const fmt = (v, dec) => v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

function countUp(el) {
  const end = Number(el.dataset.count), dec = Number(el.dataset.dec || 0), t0 = performance.now(), dur = 1200;
  const frame = now => {
    const p = Math.min(1, (now - t0) / dur);
    el.textContent = fmt(end * (1 - Math.pow(1 - p, 3)), dec);   // ease-out
    if (p < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function play(step) {
  if (step.classList.contains("in")) return;
  step.classList.add("in");
  if (calm) return;   // finished state straight away: numbers already final, no moving dots
  step.querySelectorAll("[data-count]").forEach(el => setTimeout(() => countUp(el), Number(el.dataset.delay || 300)));
  step.querySelectorAll("animateMotion").forEach(a => a.beginElement());
}

if (calm) steps.forEach(play);
else {
  document.querySelectorAll("[data-count]").forEach(el => { el.textContent = fmt(0, Number(el.dataset.dec || 0)); });
  const reveal = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { play(e.target); reveal.unobserve(e.target); }
  }), { threshold: 0.25 });
  steps.forEach(s => reveal.observe(s));
}

// which step is in the middle of the screen -> highlight its dot
let current = -1;
const next = document.getElementById("next");
const middle = new IntersectionObserver(entries => entries.forEach(e => {
  if (!e.isIntersecting) return;
  current = steps.indexOf(e.target);
  dots.forEach((d, i) => i === current ? d.setAttribute("aria-current", "step") : d.removeAttribute("aria-current"));
  const last = current === steps.length - 1;
  next.querySelector("span").textContent = last ? "Top" : "Next";
  next.setAttribute("aria-label", last ? "Back to step 1" : "Next step");
  next.classList.toggle("top", last);
}), { rootMargin: "-45% 0px -45% 0px" });
steps.forEach(s => middle.observe(s));

function go(i) {
  const step = steps[i];
  play(step);
  step.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
  step.querySelector("h2").focus({ preventScroll: true });   // keyboard and screen-reader users land on the step
}
next.addEventListener("click", () => go(current >= steps.length - 1 ? 0 : current + 1));
dots.forEach((d, i) => d.addEventListener("click", e => { e.preventDefault(); go(i); }));
window.HIW = { go: id => go(Math.max(0, steps.indexOf(document.getElementById(id)))) };   // used by the dashboard overlay
if (embedded) {
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeOverlay(); });
  document.querySelectorAll('a[href="./"]').forEach(a => a.addEventListener("click", e => { e.preventDefault(); closeOverlay(); }));
}
document.querySelectorAll(".overview a").forEach(a => a.addEventListener("click", e => {
  e.preventDefault(); go(steps.indexOf(document.querySelector(a.getAttribute("href"))));
}));
