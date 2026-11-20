"""Live dashboard: replay the cache simulation hour by hour.

Run from the project root:  streamlit run dashboard/app.py
"""
from __future__ import annotations
from pathlib import Path
import altair as alt
import pandas as pd
import streamlit as st
from pcache.data import generate_requests
from pcache.report import align, mean_abs_error, precision_at_k, top_k_table
from pcache.simulator import POLICY_NAMES, iter_region

K = 10
MATCH = "background-color: #c8e6c9; color: #1b5e20; font-weight: 600"
alt.data_transformers.disable_max_rows()
st.set_page_config(page_title="Predictive CDN Cache", page_icon="📡", layout="wide")


@st.cache_data(show_spinner="Loading request log…")
def load(source: str, path: str) -> pd.DataFrame:
    return generate_requests() if source == "Synthetic" else pd.read_csv(path)


# ---------- sidebar ----------
sb = st.sidebar
sb.header("Settings")
source = sb.radio("Data", ["Synthetic", "CSV file"])
path = sb.text_input("CSV path", "data/wiki_requests.csv", disabled=source == "Synthetic")
if source == "CSV file" and not Path(path).exists():
    st.error(f"File not found: {path}. Run `python scripts/prepare_wikipedia.py` first.")
    st.stop()
df = load(source, path)
region = sb.selectbox("Region", sorted(df["region"].unique()))
capacity = sb.number_input("Cache capacity (videos)", 10, 5000, 200, step=10)
speed = sb.slider("Playback speed (hours / second)", 0.25, 5.0, 1.0, 0.25)
c1, c2, c3 = sb.columns(3)
start, pause, reset = c1.button("▶ Start"), c2.button("⏸ Pause"), c3.button("↺ Reset")

state = st.session_state
config = (source, path, region, capacity)
if reset or state.get("config") != config:
    state.update(config=config, gen=None, history=[], last=None, prev=None, running=False, done=False)
if start and not state.done:
    state.running = True
if pause:
    state.running = False

region_df = df[df["region"] == region]
n_test = region_df["hour"].nunique() - region_df["hour"].nunique() // 2


def advance() -> None:
    """Step the simulation forward one test hour (fast-forwarding warm-up the first time)."""
    if state.gen is None:
        with st.spinner("Replaying warm-up hours and training the model…"):
            state.gen = iter_region(region_df, int(capacity))
            r = next(state.gen)
            while not r.is_test:
                r = next(state.gen)
    else:
        try:
            r = next(state.gen)
        except StopIteration:
            state.running, state.done = False, True
            st.rerun()
    state.prev = state.last
    state.last = r
    state.history.append({"hour": r.hour, **{p: r.running_hit_rate[p] * 100 for p in POLICY_NAMES}})


def highlight(t: pd.DataFrame) -> pd.DataFrame:
    styles = pd.DataFrame("", index=t.index, columns=t.columns)
    styles.loc[t["predicted_video"].isin(t["actual_video"]), ["predicted_video", "predicted_count"]] = MATCH
    styles.loc[t["actual_video"].isin(t["predicted_video"]), ["actual_video", "actual_count"]] = MATCH
    return styles


def quality(r) -> tuple[float, float]:
    return precision_at_k(r.predicted, r.actual, K), mean_abs_error(r.predicted, r.actual)


def render() -> None:
    st.title("📡 Predictive CDN Cache — live replay")
    r = state.last
    if r is None:
        st.info("Choose data, region and capacity in the sidebar, then press **▶ Start**. "
                "The first half of the hours is used to train the model (warm-up); "
                "the replay shows the second half, which the model has never seen.")
        return
    i = len(state.history)
    status = "finished" if state.done else ("playing" if state.running else "paused")
    st.progress(i / n_test, text=f"{region} · hour {r.hour} · test hour {i} of {n_test} · {status}")

    prec, mae = quality(r)
    lead = r.running_hit_rate["Hybrid"] - r.running_hit_rate["LFU"]
    d_prec = d_mae = d_lead = None
    if state.prev is not None and state.prev.is_test:
        p_prec, p_mae = quality(state.prev)
        d_prec, d_mae = f"{prec - p_prec:+.0%}", f"{mae - p_mae:+.3f}"
        d_lead = f"{(lead - (state.prev.running_hit_rate['Hybrid'] - state.prev.running_hit_rate['LFU'])) * 100:+.2f} pp"
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"Precision@{K} (this hour)", f"{prec:.0%}", d_prec,
              help="Share of the model's top-10 predicted videos that really were in the top 10.")
    m2.metric("Mean absolute error", f"{mae:.3f}", d_mae, delta_color="inverse",
              help="Average gap between predicted and real request count per video (lower is better).")
    m3.metric("Hybrid lead over LFU", f"{lead * 100:+.2f} pp", d_lead,
              help="Running hit-rate difference in percentage points since the test period began.")
    m4.metric("Hybrid running hit rate", f"{r.running_hit_rate['Hybrid']:.1%}")

    st.subheader("Running hit rate per policy (%)")
    st.line_chart(pd.DataFrame(state.history).set_index("hour"), height=280)

    left, right = st.columns([1, 1])
    with left:
        st.subheader(f"Top {K}: predicted vs actual (hour {r.hour})")
        st.caption("Green = video appears in both lists.")
        table = top_k_table(r.predicted, r.actual, K)
        st.dataframe(table.style.apply(highlight, axis=None).format({"predicted_count": "{:.1f}"}),
                     hide_index=True, width="stretch")
    with right:
        st.subheader(f"Predicted vs actual requests (hour {r.hour})")
        st.caption("One dot per video. Dots on the red line were predicted perfectly.")
        pts = align(r.predicted, r.actual).rename_axis("video").reset_index()
        hi = float(max(pts["actual"].max(), pts["predicted"].max())) * 1.05
        dots = alt.Chart(pts).mark_circle(size=25, opacity=0.4).encode(
            x=alt.X("actual:Q", title="actual requests", scale=alt.Scale(domain=[0, hi])),
            y=alt.Y("predicted:Q", title="predicted requests", scale=alt.Scale(domain=[0, hi])),
            tooltip=["video", "actual", alt.Tooltip("predicted:Q", format=".1f")])
        line = alt.Chart(pd.DataFrame({"x": [0, hi], "y": [0, hi]})).mark_line(color="red").encode(x="x", y="y")
        st.altair_chart(dots + line, width="stretch")


@st.fragment(run_every=1 / speed if state.running else None)
def live() -> None:
    if state.running:
        advance()
    render()


live()
