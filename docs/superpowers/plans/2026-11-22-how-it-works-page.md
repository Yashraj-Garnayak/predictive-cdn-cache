# "How it works" Page: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a 10-step, scroll-driven animated explainer at `web/how-it-works.html`, linked from the
dashboard header.

**Architecture:** static HTML, CSS and JS served by the existing `StaticFiles` mount.
- An IntersectionObserver adds `.in` to each `<section class="step">` as it enters the view.
- CSS transitions and keyframes animate the SVG and HTML visuals.
- A tiny counter animates numbers marked `data-count`.
- With reduced motion, `.in` is applied at once and transitions are disabled.

**Tech Stack:** HTML, CSS, vanilla JS, inline SVG. No libraries.

**Spec:** `docs/superpowers/specs/2026-11-22-how-it-works-page-design.md`

## Global Constraints
- Colours come from the `web/style.css` tokens (`--hybrid`, `--lfu`, `--predictive`, `--lru`,
  `--hit`, `--miss`). The page loads `style.css` plus its own `how-it-works.css`.
- Every number and rule must match the spec's "Facts the page must match" list.
- No new libraries. No changes to API code. No commits.

## Review Focus
1. Reduced motion: all content visible in its final state, nothing stuck at opacity 0. Checked
   by screenshot with emulated reduced motion.
2. Phone width (390 px): no horizontal scroll, SVGs scale down. Checked by screenshot.
3. Keyboard: Next button, dots and overview items reachable with Tab, visible focus. Checked
   manually.
4. JS fails or loads late: content still readable (`.in` is only an enhancement; the `no-js`
   default shows everything).
5. The direct URL `/how-it-works.html` and the link from `/` both work. Tested in Task 1.

---

### Task 1: Route test and header link
**Files:**
- Modify `web/index.html`: add `<a class="btn" href="how-it-works.html">How it works</a>` in
  `.buttons`.
- Modify `tests/test_api.py`.
- Create a stub `web/how-it-works.html`.

- [ ] **Step 1:** Write `test_how_it_works_page_served_and_linked`. `GET /how-it-works.html` is
  200 and contains "How it works"; `GET /` contains `href="how-it-works.html"`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_api.py -q`. Expect FAIL (404).
- [ ] **Step 3:** Add the link and the stub page.
- [ ] **Step 4:** Rerun. Expect PASS.

### Task 2: The page (structure, styles, animation engine, 10 steps)
**Files:** Create `web/how-it-works.html`, `web/how-it-works.css` and `web/how-it-works.js`.

- [ ] **Step 1:** Write the HTML with 10 `<section class="step" id="s1..s10">` elements. Each has a
  visual, an `<h2>` and a `<p>`, with the spec's facts as copy. Add a fixed nav with dots (links
  to `#sN`) and a Next button. The overview (s10) uses links to `#s1..#s9`.
- [ ] **Step 2:** Write the CSS:
  - Shared glass card layout.
  - `.reveal` items with `--i` stagger delays.
  - `.draw` paths using `stroke-dasharray` / `stroke-dashoffset`.
  - Keyframes for step 1's request dots and step 7's loop.
  - A `prefers-reduced-motion` override that shows final states.
  - A layout breakpoint at 640 px.
- [ ] **Step 3:** Write the JS:
  - The observer that adds `.in` and starts the counters.
  - Dot highlighting for the active step.
  - Next scrolls to the next step.
  - A reduced-motion path that sets everything to its final state.

### Task 3: Screenshot check and fixes
- [ ] Serve with uvicorn. Screenshot every step at 1440 px and 390 px, and once with reduced
  motion. Fix what's broken.
- [ ] Run `.venv/bin/python -m pytest -q`. Expect everything to pass.
