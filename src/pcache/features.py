"""Hourly per-video features for popularity forecasting."""
from __future__ import annotations
import pandas as pd

LAGS = (1, 2, 3, 6)
FEATURES = [f"lag_{l}" for l in LAGS] + ["growth", "rolling_mean_6"]


def hourly_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Matrix: rows=hour, cols=video_id, values=request count (one region)."""
    return df.groupby(["hour", "video_id"]).size().unstack(fill_value=0).sort_index()


def build_features(counts: pd.DataFrame, hour: int) -> pd.DataFrame:
    """Features describing each video using only data before `hour`."""
    cols = {}
    for l in LAGS:
        h = hour - l
        cols[f"lag_{l}"] = counts.loc[h] if h in counts.index else 0
    feats = pd.DataFrame(cols, index=counts.columns).fillna(0)
    feats["growth"] = feats["lag_1"] - feats["lag_2"]
    window = counts.loc[max(0, hour - 6): hour - 1]
    feats["rolling_mean_6"] = window.mean() if len(window) else 0
    return feats.fillna(0)


def training_set(counts: pd.DataFrame, hours: range) -> tuple[pd.DataFrame, pd.Series]:
    X, y = [], []
    for h in hours:
        f = build_features(counts, h)
        f = f[f.sum(axis=1) > 0]
        X.append(f)
        y.append(counts.loc[h].reindex(f.index).fillna(0))
    return pd.concat(X), pd.concat(y)
