"""Synthetic regional request-log generator and CSV loader."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

# Compact dtypes: a 140M-row trace takes ~1.3 GB instead of ~4 GB
CSV_DTYPES = {"region": "category", "hour": "int32", "video_id": "int32"}


def load_requests(path) -> pd.DataFrame:
    """Read a region,hour,video_id[,requests] CSV (e.g. data/wiki_requests.csv) with memory-light dtypes.
    Raises ValueError for anything that is not such a file (a folder, wrong columns, …)."""
    dtypes = _csv_columns(path)
    try:
        return pd.read_csv(path, dtype=dtypes, usecols=list(dtypes))
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as e:
        raise ValueError(f"{path} is not a region,hour,video_id CSV ({e})") from e


def _csv_columns(path) -> dict:
    """dtypes to read from a region,hour,video_id[,requests] CSV; ValueError if it is not one."""
    if not Path(path).is_file():
        raise ValueError(f"{path} is not a file")
    try:
        header = set(pd.read_csv(path, nrows=0).columns)
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as e:
        raise ValueError(f"{path} is not a CSV ({e})") from e
    if not set(CSV_DTYPES) <= header:
        raise ValueError(f"{path} needs columns region,hour,video_id (optionally requests)")
    return {**CSV_DTYPES, "requests": "int64"} if "requests" in header else CSV_DTYPES


def csv_regions(path) -> list[str]:
    _csv_columns(path)
    return sorted(map(str, pd.read_csv(path, usecols=["region"], dtype="category")["region"].cat.categories))


def load_csv_region(path, region: str) -> pd.DataFrame:
    """Only one region's rows, read in chunks so the whole file is never in memory at once.
    Works for one-row-per-request files and for hourly counts (a `requests` column)."""
    dtypes = _csv_columns(path)
    chunks = pd.read_csv(path, usecols=list(dtypes), dtype=dtypes, chunksize=2_000_000)
    df = pd.concat([c[c["region"] == region] for c in chunks], ignore_index=True)
    if df.empty:
        raise ValueError(f"region {region!r} not found in {path}")
    return df


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
