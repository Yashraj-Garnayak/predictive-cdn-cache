"""Hourly per-video features for popularity forecasting."""
from __future__ import annotations
import pandas as pd

LAGS = (1, 2, 3, 6, 24)
FEATURES = [f"lag_{l}" for l in LAGS] + ["growth", "rolling_mean_6", "hour_of_day"]


def hourly_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Matrix: rows=hour, cols=video_id, values=request count (one region).
    `df` is one row per request, or already-counted rows with a `requests` column."""
    g = df.groupby(["hour", "video_id"])
    s = g["requests"].sum() if "requests" in df else g.size()
    return s.unstack(fill_value=0).sort_index()


def build_features(counts: pd.DataFrame, hour: int) -> pd.DataFrame:
    """Features for every video seen in the last 6 hours or exactly 24 hours ago,
    using only data before `hour`."""
    cols = {}
    for l in LAGS:
        h = hour - l
        cols[f"lag_{l}"] = counts.loc[h] if h in counts.index else 0
    feats = pd.DataFrame(cols, index=counts.columns).fillna(0)
    feats["growth"] = feats["lag_1"] - feats["lag_2"]
    window = counts.loc[max(0, hour - 6): hour - 1]
    feats["rolling_mean_6"] = window.mean() if len(window) else 0
    feats = feats.fillna(0)
    feats["hour_of_day"] = hour % 24  # hours count from the trace start, so this is offset but consistent
    return feats[(feats["rolling_mean_6"] > 0) | (feats["lag_24"] > 0)]


def training_set(counts: pd.DataFrame, hours: range) -> tuple[pd.DataFrame, pd.Series]:
    X, y = [], []
    for h in hours:
        f = build_features(counts, h)
        X.append(f)
        y.append(counts.loc[h].reindex(f.index).fillna(0))
    return pd.concat(X), pd.concat(y)


def rich_features(counts: pd.DataFrame, hour: int, *, static: pd.DataFrame | None = None,
                  other: pd.DataFrame | None = None, weekly: bool = False) -> pd.DataFrame:
    """build_features plus trend, age and optional columns, for the prefetch classifier.
    Uses only hours before `hour`. `static`: size_bytes/content_type per video_id. `other`: summed
    counts of the other regions (same layout as `counts`). `weekly`: add lag_168 and day_of_week."""
    feats = build_features(counts, hour)
    past = counts.loc[:hour - 1]
    feats["ewm_6"] = past.ewm(span=6).mean().iloc[-1].reindex(feats.index)
    first_seen = (past > 0).idxmax()  # first hour with a request (candidates always have one)
    feats["hours_since_first_seen"] = (hour - first_seen.reindex(feats.index)).astype(float)
    if static is not None:
        feats = feats.join(static, how="left")
    if weekly:
        week_ago = counts.loc[hour - 168] if hour - 168 in counts.index else pd.Series(0, index=counts.columns)
        feats["lag_168"] = week_ago.reindex(feats.index).fillna(0)
        feats["day_of_week"] = (hour // 24) % 7
    if other is not None:
        feats["other_regions_recent"] = other.loc[hour - 6: hour - 1].sum().reindex(feats.index).fillna(0)
    return feats


def optional_flags(df: pd.DataFrame, train_hours: int) -> dict:
    """Which optional features the data supports: weekly needs a week of training history,
    cross-region needs some video_id seen in two or more regions."""
    shared = df.groupby("video_id", observed=True)["region"].nunique().gt(1).any()
    return {"weekly": train_hours >= 168, "cross_region": bool(shared)}


def static_info(df: pd.DataFrame) -> pd.DataFrame | None:
    """size_bytes / content_type per video_id, when the source has them."""
    cols = [c for c in ("size_bytes", "content_type") if c in df]
    return df.drop_duplicates("video_id").set_index("video_id")[cols] if cols else None
