"""Synthetic regional request-log generator."""
from __future__ import annotations
import numpy as np
import pandas as pd


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
