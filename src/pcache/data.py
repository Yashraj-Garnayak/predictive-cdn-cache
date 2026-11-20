"""Synthetic regional request-log generator and CSV loader."""
from __future__ import annotations
import numpy as np
import pandas as pd

# Compact dtypes: a 140M-row trace takes ~1.3 GB instead of ~4 GB
CSV_DTYPES = {"region": "category", "hour": "int32", "video_id": "int32"}


def load_requests(path) -> pd.DataFrame:
    """Read a region,hour,video_id CSV (e.g. data/wiki_requests.csv) with memory-light dtypes."""
    return pd.read_csv(path, dtype=CSV_DTYPES)


def generate_requests(regions=("Frankfurt", "Mumbai", "Virginia"), hours=72,
                      n_videos=20000, requests_per_hour=2000, viral_per_hour=10,
                      seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for region in regions:
        base = 1 / np.arange(1, n_videos + 1) ** 0.8
        rng.shuffle(base)
        base /= base.sum()
        trends: dict[int, int] = {}
        for h in range(hours):
            for v in rng.choice(n_videos, viral_per_hour, replace=False):
                trends[int(v)] = h
            p = base.copy()
            for v, start in trends.items():
                age = h - start
                if 0 <= age < 8:
                    p[v] += 0.004 * np.exp(-((age - 3) ** 2) / 4)
            p /= p.sum()
            for v in rng.choice(n_videos, requests_per_hour, p=p):
                rows.append((region, h, int(v)))
    return pd.DataFrame(rows, columns=["region", "hour", "video_id"])
