"""Replay request logs against cache policies."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Iterator
import pandas as pd
from .features import hourly_counts
from .model import PopularityModel
from .policies import LRUCache, LFUCache, PredictiveCache, HybridCache

log = logging.getLogger(__name__)
POLICY_NAMES = ["LRU", "LFU", "Predictive", "Hybrid"]


@dataclass
class HourResult:
    """Snapshot of one region's simulation after one hour of requests."""
    hour: int
    is_test: bool                       # False during warm-up (the model's training hours)
    hourly_hit_rate: dict[str, float]   # hit rate within this hour only
    running_hit_rate: dict[str, float]  # hit rate since the start of the current phase
    actual: pd.Series                   # video_id -> requests this hour
    predicted: pd.Series | None         # video_id -> predicted requests (test hours only)


def iter_region(df: pd.DataFrame, capacity: int, train_frac: float = 0.5) -> Iterator[HourResult]:
    """Replay one region hour by hour, yielding a HourResult after each hour."""
    hours = sorted(df["hour"].unique())
    split = hours[int(len(hours) * train_frac)]
    counts = hourly_counts(df)
    model = PopularityModel().fit(counts, range(hours[0] + 6, split))

    policies = [LRUCache(capacity), LFUCache(capacity), PredictiveCache(capacity), HybridCache(capacity)]
    for h, group in df.groupby("hour", sort=True):
        predicted = None
        if h >= split:
            predicted = model.predict(counts, h)
            for pred in policies[2:]:
                pred.prefetch(int(v) for v in predicted.nlargest(pred.prefetch_size).index)
        before = {p.name: (p.hits, p.requests) for p in policies}
        for vid in group["video_id"]:
            for p in policies:
                p.request(int(vid))
        hourly = {p.name: (p.hits - before[p.name][0]) / max(1, p.requests - before[p.name][1])
                  for p in policies}
        yield HourResult(int(h), bool(h >= split), hourly,
                         {p.name: p.hit_rate for p in policies}, counts.loc[h], predicted)
        if h == split - 1:  # end of warm-up: reset scores
            for p in policies:
                p.hits = 0
                p.requests = 0


def simulate_region(df: pd.DataFrame, capacity: int, train_frac: float = 0.5) -> dict[str, float]:
    last = None
    for last in iter_region(df, capacity, train_frac):
        pass
    return last.running_hit_rate


def simulate(df: pd.DataFrame, capacity: int) -> pd.DataFrame:
    results = {}
    for region, g in df.groupby("region"):
        log.info("simulating %s", region)
        results[region] = simulate_region(g, capacity)
    return (pd.DataFrame(results).T * 100).round(2)
