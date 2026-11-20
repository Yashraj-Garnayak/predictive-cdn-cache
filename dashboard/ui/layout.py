"""Draw each section of the live view. Styling lives in theme.py; data shaping in content.py."""
from __future__ import annotations
import base64, json
from functools import cache
from html import escape
from pathlib import Path
import altair as alt
import pandas as pd
import streamlit as st
from . import theme
from .content import K, N_BUBBLES

BUBBLES_HEIGHT = 520


def inject_css() -> None:
    st.html(theme.page_css())


# ---------- 1. header bar ----------
def header(source_label: str, regions: list[str]) -> tuple[str, bool, bool, bool]:
    """Title, data source, region picker and Start / Pause / Reset. Returns (region, start, pause, reset)."""
    with st.container(key="lv_header"):
        left, mid, right = st.columns([2.4, 1.2, 2.4], vertical_alignment="center")
        left.html(f'<div class="lv-title">Predictive CDN Cache</div>'
                  f'<div class="lv-sub">Live view · <b>{escape(source_label)}</b></div>')
        region = mid.selectbox("Region", regions, key="lv_region", label_visibility="collapsed")
        b1, b2, b3 = right.columns(3)
        start = b1.button("▶  Start", key="lv_start", width="stretch", type="primary")
        pause = b2.button("❙❙  Pause", key="lv_pause", width="stretch")
        reset = b3.button("↺  Reset", key="lv_reset", width="stretch")
    return region, start, pause, reset


def progress_html(done: int, total: int, hour: int | None, status: str, prev_done: int | None = None) -> str:
    """Progress strip: how far through the held-out (test) hours the replay is."""
    to = 100 * done / max(1, total)
    frm = to if prev_done is None else 100 * prev_done / max(1, total)
    where = f"Hour <b>{hour}</b> · test hour <b>{done}</b> of {total}" if hour is not None else \
        f"<b>{total}</b> test hours ready to replay"
    return (f'<div class="lv-progress"><div class="lv-progress-row"><span>{where}</span>'
            f'<span class="lv-status"><span class="lv-dot {status}"></span>{status.capitalize()}</span></div>'
            f'<div class="lv-track"><div class="lv-fill" style="--from:{frm:.2f}%;--to:{to:.2f}%;width:{to:.2f}%">'
            f'</div></div></div>')


def progress(done: int, total: int, hour: int | None, status: str, prev_done: int | None = None) -> None:
    st.html(progress_html(done, total, hour, status, prev_done))


# ---------- 2. metric cards ----------
def metric_cards_html(cards: list[dict]) -> str:
    """cards: dicts with label, value, tip, accent and optional delta=(text, 'good'|'bad'|'flat')."""
    out = []
    for c in cards:
        d = c.get("delta")
        chip = f'<span class="lv-delta {d[1]}">{escape(d[0])}</span>' if d else ""
        out.append(f'<div class="lv-metric" style="--accent:{c["accent"]}">'
                   f'<div class="lv-metric-label">{escape(c["label"])}'
                   f'<span class="lv-info">i<span class="lv-tip">{escape(c["tip"])}</span></span></div>'
                   f'<div class="lv-metric-value">{c["value"]}</div>{chip}</div>')
    return f'<div class="lv-metrics">{"".join(out)}</div>'


def metric_cards(cards: list[dict]) -> None:
    st.html(metric_cards_html(cards))


# ---------- 3a. Trending Now bubbles ----------
@cache
def _bubbles_page() -> str:
    # The frame's HTML never changes, so Streamlit keeps the same iframe alive between hours.
    html = (Path(__file__).with_name("bubbles.html")).read_text(encoding="utf-8")
    return html.replace("/*THEME*/", theme.css_vars())


def encode_bubbles(data: list[dict]) -> str:
    """Bubble data as base64 JSON, safe to place as text inside the page."""
    return base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")


def bubbles(data: list[dict]) -> None:
    with st.container(key="lv_bubbles"):
        st.html(f'<div class="lv-h">Trending now</div>'
                f'<div class="lv-hsub">This hour\'s {N_BUBBLES} most-requested videos · bubble size = requests</div>')
        st.iframe(_bubbles_page(), height=BUBBLES_HEIGHT)  # replaces the deprecated components.v1.html
        # Hidden hand-off: the bubble frame reads this every 250 ms and animates to the new data.
        st.html(f'<div class="pcache-bubble-data">{encode_bubbles(data)}</div>'
                f'<div class="lv-legend"><span><i style="background:{theme.GREEN}"></i>Model had it in its top {N_BUBBLES} picks</span>'
                f'<span><i style="background:{theme.PINK}"></i>Model missed it</span>'
                f'<span>Hover a bubble for details · move the mouse to push them</span></div>')


# ---------- 3b. predicted vs actual table ----------
def _fmt(v: float | None, digits: int) -> str:
    return "" if v is None else f"{v:,.{digits}f}"


def table_html(rows: list[dict], hour: int) -> str:
    body = []
    for r in rows:
        p_cls = "match" if r["pred_match"] else "none"
        a_cls = "match" if r["act_match"] else "miss"
        body.append(
            f'<tr><td class="rank">{r["rank"]}</td>'
            f'<td class="cell {"match" if r["pred_match"] else ""}" title="{escape(r["pred_title"])}">'
            f'<span class="lv-pip {p_cls}"></span>{escape(r["pred_title"])}</td>'
            f'<td class="num">{_fmt(r["pred_count"], 1)}</td><td class="gap"></td>'
            f'<td class="cell {a_cls}" title="{escape(r["act_title"])}">'
            f'<span class="lv-pip {a_cls}"></span>{escape(r["act_title"])}</td>'
            f'<td class="num">{_fmt(r["act_count"], 0)}</td></tr>')
    return (f'<div class="lv-h">Predicted vs actual · top {K}</div>'
            f'<div class="lv-hsub">Hour {hour} · green = in both lists, pink = the model missed it</div>'
            f'<table class="lv-table"><colgroup><col style="width:26px"><col><col style="width:50px">'
            f'<col style="width:8px"><col><col style="width:46px"></colgroup>'
            f'<thead><tr><th></th><th>Model expected</th><th style="text-align:right">guess</th><th></th>'
            f'<th>What really happened</th><th style="text-align:right">views</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def top10_table(rows: list[dict], hour: int) -> None:
    with st.container(key="lv_table"):
        st.html(table_html(rows, hour))


# ---------- 4. hit-rate chart ----------
def hit_rate_chart_spec(history: list[dict]) -> alt.LayerChart:
    df = pd.DataFrame(history).melt("hour", var_name="policy", value_name="hit rate (%)")
    names = list(theme.POLICY_COLORS)
    color = alt.Color("policy:N", scale=alt.Scale(domain=names, range=list(theme.POLICY_COLORS.values())),
                      legend=alt.Legend(orient="top", title=None, labelColor=theme.TEXT, labelFontSize=13,
                                        symbolType="circle", symbolSize=90, columnPadding=20))
    base = alt.Chart(df).encode(
        x=alt.X("hour:Q", title="hour", axis=alt.Axis(tickMinStep=1, format="d")),
        y=alt.Y("hit rate (%):Q", title=None, scale=alt.Scale(zero=False, nice=True)),
        color=color)
    lines = base.mark_line(interpolate="monotone").encode(
        strokeWidth=alt.condition(alt.datum.policy == "Hybrid", alt.value(3.5), alt.value(2)))
    last = base.mark_circle(size=70, opacity=1).transform_window(
        rank="rank()", sort=[alt.SortField("hour", order="descending")], groupby=["policy"]
    ).transform_filter(alt.datum.rank == 1).encode(
        tooltip=["policy:N", "hour:Q", alt.Tooltip("hit rate (%):Q", format=".2f")])
    return (lines + last).properties(height=300, background="transparent").configure_view(stroke=None).configure_axis(
        labelColor=theme.MUTED, titleColor=theme.MUTED, gridColor="rgba(255,255,255,0.06)", domain=False,
        tickColor="rgba(255,255,255,0.06)", labelFont=theme.FONT, titleFont=theme.FONT, labelFontSize=12
    ).configure_legend(labelFont=theme.FONT)


def hit_rate_chart(history: list[dict]) -> None:
    with st.container(key="lv_chart"):
        st.html('<div class="lv-h">Hit rate so far, per policy</div>'
                '<div class="lv-hsub">Share of requests served straight from the cache since the test hours began (%)</div>')
        st.altair_chart(hit_rate_chart_spec(history), theme=None, width="stretch")


# ---------- empty state ----------
def intro(n_test: int) -> None:
    st.html('<div class="lv-metric lv-empty"><h2>Watch the cache think.</h2>'
            '<p>Press <b>Start</b> to replay the traffic hour by hour. The first half of the hours trains the '
            'model (that part is skipped instantly); the replay then shows the other '
            f'{n_test} hours, which the model has never seen. Bubbles show what is trending; '
            'green means the model saw it coming.</p></div>')
