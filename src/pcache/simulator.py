"""Replay request logs against cache policies."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Iterator
import numpy as np
import pandas as pd
from .features import hourly_counts, static_info
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
    byte_hit_rate: dict[str, float] = field(default_factory=dict)  # running, like running_hit_rate; 0 without sizes
    hit_precision: float | None = None  # prefetch model: share of its top 10 requested this hour (test hours)


def hour_requests(group: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    """Video ids of one hour's requests in replay order. Hourly counts are interleaved randomly,
    not each video back to back; one-row-per-request data keeps its own order."""
    vids = group["video_id"].to_numpy()
    if "requests" in group:
        vids = rng.permutation(np.repeat(vids, group["requests"].to_numpy()))
    return vids


def iter_region(df: pd.DataFrame, capacity: int, train_frac: float = 0.5,
                policies=None, seed: int = 0, prefetch_model=None) -> Iterator[HourResult]:
    """Replay one region hour by hour, yielding a HourResult after each hour.
    `df` is one row per request, or hourly counts with a `requests` column (replayed in a seeded random order within each hour).
    `policies` overrides the default four (e.g. to compare Hybrid reserved shares).
    `prefetch_model` (a fitted PrefetchModel) ranks Hybrid's reserved share instead of the count model."""
    if prefetch_model is not None and prefetch_model.capacity != capacity:
        raise ValueError(f"prefetch_model was trained for capacity {prefetch_model.capacity}, not {capacity}")
    hours = sorted(df["hour"].unique())
    split = hours[int(len(hours) * train_frac)]
    counts = hourly_counts(df)
    model = PopularityModel().fit(counts, range(hours[0] + 6, split))

    rng = np.random.default_rng(seed)  # fixed seed: replays are reproducible
    sizes = (df.drop_duplicates("video_id").set_index("video_id")["size_bytes"].fillna(0).astype("int64").to_dict()
             if "size_bytes" in df else {})
    share = prefetch_model.prefetch_fraction if prefetch_model is not None else 0.10
    policies = policies or [LRUCache(capacity), LFUCache(capacity), PredictiveCache(capacity),
                            HybridCache(capacity, share)]
    static = static_info(df) if prefetch_model is not None else None
    for h, group in df.groupby("hour", sort=True):
        predicted = hit_precision = None
        if h >= split:
            predicted = model.predict(counts, h)
            ranked = [int(v) for v in predicted.sort_values(ascending=False).index]
            for p in policies:  # no-op for LRU/LFU
                if prefetch_model is not None and isinstance(p, HybridCache):
                    picks = prefetch_model.rank(counts, h, exclude=set(p._lru._store), static=static,
                                                other=prefetch_model.other)
                    p.prefetch(picks)
                    top = picks[:10]
                    hit_precision = float((counts.loc[h].reindex(top).fillna(0) > 0).mean()) if top else 0.0
                else:
                    p.prefetch(ranked)
        before = {p.name: (p.hits, p.requests) for p in policies}
        for vid in hour_requests(group, rng).tolist():
            size = sizes.get(vid, 0)
            for p in policies:
                p.request(vid, size)
        hourly = {p.name: (p.hits - before[p.name][0]) / max(1, p.requests - before[p.name][1])
                  for p in policies}
        yield HourResult(int(h), bool(h >= split), hourly,
                         {p.name: p.hit_rate for p in policies}, counts.loc[h], predicted,
                         {p.name: p.byte_hit_rate for p in policies}, hit_precision)
        if h == split - 1:  # end of warm-up: reset scores
            for p in policies:
                p.hits = p.requests = p.bytes_hit = p.bytes_requested = 0


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
