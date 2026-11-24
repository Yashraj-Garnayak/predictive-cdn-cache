"""One standard input format for every data source, plus a small adapter per source.

Standard columns: region, hour, object_id, requests (optional: size_bytes, content_type).
One row per (region, hour, object_id). `object_id` means the same object in every region.
How to add a source: docs/data-sources.md.
"""
from __future__ import annotations
from typing import Callable
import pandas as pd

STANDARD = ["region", "hour", "object_id", "requests"]
OPTIONAL = ["size_bytes", "content_type"]


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Check a standard frame and return it with compact dtypes; ValueError names the problem."""
    missing = [c for c in STANDARD if c not in df]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    hour = pd.to_numeric(df["hour"], errors="coerce")
    if hour.isna().any() or (hour < 0).any() or (hour % 1 != 0).any():
        raise ValueError("hour must be a whole number >= 0 in every row")
    req = pd.to_numeric(df["requests"], errors="coerce")
    if req.isna().any() or (req <= 0).any() or (req % 1 != 0).any():
        raise ValueError("requests must be a positive whole number in every row")
    oid = pd.to_numeric(df["object_id"], errors="coerce")
    if oid.isna().any() or (oid % 1 != 0).any():
        raise ValueError("object_id must be a whole number in every row")
    if "size_bytes" in df:  # empty = unknown (counts as 0 bytes); otherwise a number >= 0
        size = pd.to_numeric(df["size_bytes"], errors="coerce")
        if (size < 0).any() or (size.isna() & df["size_bytes"].notna()).any():
            raise ValueError("size_bytes must be empty or a number >= 0")
    dup = df.duplicated(["region", "hour", "object_id"])
    if dup.any():
        raise ValueError(f"{int(dup.sum())} duplicate (region, hour, object_id) row(s)")
    out = df[[c for c in STANDARD + OPTIONAL if c in df]].copy()
    return out.astype({"region": "category", "hour": "int32", "object_id": "int64", "requests": "int64"})


def _shared_ids(titles: pd.DataFrame) -> pd.DataFrame:
    """Per-region video_id -> one object_id per title, shared across regions."""
    if (titles["title"].astype(str).str.strip() == "").any():
        raise ValueError("blank title in the titles file: objects could not be told apart")
    return titles.assign(object_id=pd.factorize(titles["title"])[0])


def meta(requests_path, titles_path) -> pd.DataFrame:
    """Meta CDN traces prepared by scripts/prepare_cachemon.py (hourly counts + object details)."""
    req = pd.read_csv(requests_path, dtype={"region": "category"})
    titles = _shared_ids(pd.read_csv(titles_path, dtype={"title": str}, keep_default_na=False))
    df = req.merge(titles[["region", "video_id", "object_id", "size_bytes", "content_type"]],
                   on=["region", "video_id"], how="left", validate="many_to_one")
    if df["object_id"].isna().any():
        raise ValueError("some requests have no matching row in the titles file")
    return validate(df)


def wikipedia(requests_path, titles_path) -> pd.DataFrame:
    """Wikipedia pageviews prepared by scripts/prepare_wikipedia.py (one row per request)."""
    raw = pd.read_csv(requests_path)
    titles = _shared_ids(pd.read_csv(titles_path, dtype={"title": str}, keep_default_na=False))
    counts = raw.groupby(["region", "hour", "video_id"]).size().rename("requests").reset_index()
    df = counts.merge(titles[["region", "video_id", "object_id"]], on=["region", "video_id"],
                      how="left", validate="many_to_one")
    if df["object_id"].isna().any():
        raise ValueError("some requests have no matching row in the titles file")
    return validate(df)


def hourly_csv(path) -> pd.DataFrame:
    """A CSV already in the standard format."""
    return validate(pd.read_csv(path))


ADAPTERS: dict[str, Callable[..., pd.DataFrame]] = {"meta": meta, "wikipedia": wikipedia, "hourly_csv": hourly_csv}


def load_source(name: str, *paths) -> pd.DataFrame:
    """Run one adapter and hand the result to the simulator."""
    if name not in ADAPTERS:
        raise ValueError(f"unknown source {name!r}; known: {', '.join(ADAPTERS)}")
    # shortcut: internal code still says video_id, rename internals if a second id kind appears
    return ADAPTERS[name](*paths).rename(columns={"object_id": "video_id"})
