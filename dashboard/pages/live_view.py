"""Live view: redesigned replay page (Trending Now bubbles, glass cards).

Opens as the second page of:  streamlit run dashboard/app.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))  # make dashboard/ui importable
from ui import content, layout, theme  # noqa: E402
from pcache.data import generate_requests  # noqa: E402
from pcache.report import mean_abs_error, precision_at_k  # noqa: E402
from pcache.simulator import POLICY_NAMES, iter_region  # noqa: E402

st.set_page_config(page_title="Live view · Predictive CDN Cache", page_icon="🫧", layout="wide")
layout.inject_css()


@st.cache_resource(show_spinner="Loading request log…")
def load(source: str, path: str) -> pd.DataFrame:
    return generate_requests() if source == "Synthetic" else pd.read_csv(path)


@st.cache_data
def load_titles(path: str) -> dict[str, dict[int, str]]:
    return content.read_titles(path)


# ---------- sidebar: settings only ----------
sb = st.sidebar
sb.header("Settings")
source = sb.radio("Data", ["Synthetic", "CSV file"], key="lv_source")
path = sb.text_input("Data file", "data/wiki_requests.csv", key="lv_path", disabled=source == "Synthetic")
capacity = sb.number_input("Cache capacity (videos)", 10, 5000, 200, step=10, key="lv_capacity")
speed = sb.slider("Playback speed (hours / second)", 0.25, 5.0, 1.0, 0.25, key="lv_speed")
if source == "CSV file" and not Path(path).exists():
    st.error(f"File not found: {path}. Run `python scripts/prepare_wikipedia.py` first.")
    st.stop()
df = load(source, path)
titles_file = content.titles_path(path)
all_titles = load_titles(str(titles_file)) if source == "CSV file" else {}
if source == "CSV file":
    sb.caption(f"Titles: {titles_file}" if all_titles else f"No {titles_file.name} found, showing video ids.")

source_label = "Synthetic traffic" if source == "Synthetic" else \
    ("Wikipedia pageviews · " if "wiki" in Path(path).name else "") + Path(path).name
region, start, pause, reset = layout.header(source_label, sorted(map(str, df["region"].unique())))

# ---------- simulation state (prefixed lv_ so it never clashes with app.py) ----------
state = st.session_state
config = (source, path, region, capacity)
if reset or state.get("lv_config") != config:
    state.update(lv_config=config, lv_gen=None, lv_history=[], lv_last=None, lv_prev=None,
                 lv_running=False, lv_done=False)
if start and not state.lv_done:
    state.lv_running = True
if pause:
    state.lv_running = False

region_df = df[df["region"].astype(str) == region]
n_test = region_df["hour"].nunique() - region_df["hour"].nunique() // 2
titles = all_titles.get(region, {})


def advance() -> None:
    """Step the simulation forward one test hour (fast-forwarding warm-up the first time)."""
    if state.lv_gen is None:
        with st.spinner("Replaying warm-up hours and training the model…"):
            state.lv_gen = iter_region(region_df, int(capacity))
            r = next(state.lv_gen)
            while not r.is_test:
                r = next(state.lv_gen)
    else:
        try:
            r = next(state.lv_gen)
        except StopIteration:
            state.lv_running, state.lv_done = False, True
            st.rerun()
    state.lv_prev, state.lv_last = state.lv_last, r
    state.lv_history.append({"hour": r.hour, **{p: r.running_hit_rate[p] * 100 for p in POLICY_NAMES}})


def cards(r, prev) -> list[dict]:
    prec, mae = precision_at_k(r.predicted, r.actual, content.K), mean_abs_error(r.predicted, r.actual)
    lead = (r.running_hit_rate["Hybrid"] - r.running_hit_rate["LFU"]) * 100
    hybrid = r.running_hit_rate["Hybrid"] * 100
    p = prev if prev is not None and prev.is_test else None
    return [
        {"label": f"Model picks that were right (top {content.K})", "accent": theme.GREEN,
         "value": f"{round(prec * content.K)}<small> / {content.K}</small>",
         "delta": content.delta(prec * content.K, p and precision_at_k(p.predicted, p.actual, content.K) * content.K,
                                "{:+.0f} vs last hour"),
         "tip": f"Of the {content.K} videos the model expected to be busiest this hour, "
                f"how many really were in the top {content.K}."},
        {"label": "Average guess error (views)", "accent": theme.PINK, "value": f"{mae:.2f}",
         "delta": content.delta(mae, p and mean_abs_error(p.predicted, p.actual), "{:+.2f}", higher_is_better=False),
         "tip": "On average, how far the model's guess of each video's views was from the real number. Lower is better."},
        {"label": "Hybrid's lead over LFU", "accent": theme.POLICY_COLORS["Hybrid"], "value": f"{lead:+.2f}<small> pts</small>",
         "delta": content.delta(lead, p and (p.running_hit_rate["Hybrid"] - p.running_hit_rate["LFU"]) * 100, "{:+.2f} pts"),
         "tip": "How many percentage points more requests Hybrid served from the cache than plain LFU so far."},
        {"label": "Hybrid hit rate", "accent": theme.POLICY_COLORS["Hybrid"], "value": f"{hybrid:.1f}<small>%</small>",
         "delta": content.delta(hybrid, p and p.running_hit_rate["Hybrid"] * 100, "{:+.2f} pts"),
         "tip": "Share of all requests since the test hours began that Hybrid served straight from the cache."},
    ]


def render() -> None:
    r, done = state.lv_last, len(state.lv_history)
    status = "finished" if state.lv_done else ("playing" if state.lv_running else "paused")
    layout.progress(done, n_test, r.hour if r else None, status if r else "ready",
                    prev_done=done - 1 if r else None)
    if r is None:
        layout.intro(n_test)
        return
    layout.metric_cards(cards(r, state.lv_prev))
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        layout.bubbles(content.bubble_data(r.predicted, r.actual, titles))
    with right:
        layout.top10_table(content.table_rows(r.predicted, r.actual, titles), r.hour)
    layout.hit_rate_chart(state.lv_history)


@st.fragment(run_every=1 / speed if state.lv_running else None)
def live() -> None:
    if state.lv_running:
        advance()
    render()


live()
