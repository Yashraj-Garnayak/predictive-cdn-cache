"""Prefetch classifier: which objects will be requested next hour but are NOT in the LRU cache.

Hybrid's reserved share is filled with the most likely of those, so the model only spends
slots on what LRU would miss.
"""
from __future__ import annotations
from typing import Iterable
import numpy as np
import pandas as pd
from .features import rich_features, static_info
from .policies import LRUCache
from .simulator import hour_requests


def lru_snapshots(df: pd.DataFrame, lru_capacity: int, hours: Iterable[int], seed: int = 0) -> dict[int, frozenset[int]]:
    """Keys a plain LRU holds at the START of each hour in `hours`, replayed in iter_region's order.
    Exact for training hours: Hybrid reserves nothing before the split, so its LRU part is plain LRU.
    shortcut: after the split Hybrid's LRU part also skips keys served from the reserved share;
    switch to replaying HybridCache if snapshots are ever needed for test hours."""
    wanted = set(hours)
    if not wanted:
        return {}
    rng = np.random.default_rng(seed)
    lru = LRUCache(lru_capacity)
    snaps = {}
    for h, group in df.groupby("hour", sort=True):
        if h in wanted:
            snaps[int(h)] = frozenset(lru._store)
        if h >= max(wanted):
            break
        for vid in hour_requests(group, rng).tolist():
            lru.request(vid)
    return snaps


def training_set(counts: pd.DataFrame, hours: Iterable[int], snapshots: dict[int, frozenset[int]],
                 **feature_kwargs) -> tuple[pd.DataFrame, pd.Series]:
    """Features of candidates not cached at the start of each hour; y = requests in that hour
    (label = y > 0, weight = y for the request-weighted variant)."""
    X, y = [], []
    for h in hours:
        f = rich_features(counts, h, **feature_kwargs)
        f = f[~f.index.isin(snapshots.get(h, frozenset()))]
        X.append(f)
        y.append(counts.loc[h].reindex(f.index).fillna(0) if h in counts.index else pd.Series(0, index=f.index))
    if not X:
        return pd.DataFrame(), pd.Series(dtype=float)
    return pd.concat(X), pd.concat(y)


def _estimator(name: str, params: dict):
    if name == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(random_state=0, **params)
    if name == "lgbm":  # optional: only installed if it wins (see docs/superpowers/specs)
        from lightgbm import LGBMClassifier
        return LGBMClassifier(random_state=0, verbose=-1, **params)
    raise ValueError(f"unknown estimator {name!r}")


class PrefetchModel:
    """Ranks objects not in Hybrid's LRU part by P(requested this hour)."""

    def __init__(self, capacity: int, prefetch_fraction: float = 0.10, estimator: str = "hgb",
                 max_object_bytes: int | None = None, weighted: bool = False, weekly: bool = False, **params):
        self.capacity, self.prefetch_fraction = capacity, prefetch_fraction
        self.estimator, self.params = estimator, params
        self.max_object_bytes, self.weighted, self.weekly = max_object_bytes, weighted, weekly
        self.reserved = max(1, int(capacity * prefetch_fraction))  # same split as HybridCache
        self.other: pd.DataFrame | None = None  # other regions' summed counts; data, never saved
        self.features: list[str] = []
        self.train_hours: list[int] = []
        self.meta: dict = {}
        self.model = None

    def fit(self, df: pd.DataFrame, train_hours: Iterable[int]) -> "PrefetchModel":
        from .features import hourly_counts
        self.train_hours = [int(h) for h in train_hours]
        snaps = lru_snapshots(df, max(1, self.capacity - self.reserved), self.train_hours)
        X, y = training_set(hourly_counts(df), self.train_hours, snaps,
                            static=static_info(df), other=self.other, weekly=self.weekly)
        if (y > 0).nunique() < 2:
            raise ValueError("training hours need both requested and unrequested candidates")
        self.features = list(X.columns)
        self.model = _estimator(self.estimator, self.params)
        self.model.fit(X[self.features], y > 0, sample_weight=y.clip(lower=1) if self.weighted else None)
        return self

    def rank(self, counts: pd.DataFrame, hour: int, exclude: set[int], static=None, other=None) -> list[int]:
        """Candidates best first, without `exclude` (what LRU already holds) and oversized objects."""
        f = rich_features(counts, hour, static=static, other=other, weekly=self.weekly)
        f = f[~f.index.isin(exclude)]
        if self.max_object_bytes is not None and "size_bytes" in f:
            f = f[f["size_bytes"].fillna(0) <= self.max_object_bytes]
        if f.empty:
            return []
        p = pd.Series(self.model.predict_proba(f[self.features])[:, 1], index=f.index)
        return [int(k) for k in p.sort_values(ascending=False, kind="stable").index]

    # ---------- versioned save/load: <root>/<region>/v<N>/{model.joblib, meta.json} ----------
    def save(self, root, region: str, meta: dict) -> "Path":
        import json
        from pathlib import Path
        import joblib
        base = Path(root) / str(region)
        base.mkdir(parents=True, exist_ok=True)
        n = 1 + max((int(p.name[1:]) for p in base.glob("v*") if p.name[1:].isdigit()), default=0)
        while True:  # another process may take v<n> between the scan and mkdir
            out = base / f"v{n}"
            try:
                out.mkdir()
                break
            except FileExistsError:
                n += 1
        other, self.other = self.other, None
        try:
            joblib.dump(self, out / "model.joblib")
        finally:
            self.other = other
        info = {"capacity": self.capacity, "prefetch_fraction": self.prefetch_fraction, "estimator": self.estimator,
                "params": self.params, "max_object_bytes": self.max_object_bytes, "weighted": self.weighted,
                "features": self.features, "train_hours": [self.train_hours[0], self.train_hours[-1]], **meta}
        (out / "meta.json").write_text(json.dumps(info, indent=2, default=str))
        return out

    @staticmethod
    def load(root, region: str, capacity: int, version: int | None = None) -> "PrefetchModel":
        import json
        from pathlib import Path
        import joblib
        found = []
        for p in (Path(root) / str(region)).glob("v*"):
            if p.name[1:].isdigit() and (p / "meta.json").is_file():
                meta = json.loads((p / "meta.json").read_text())
                if meta.get("capacity") == capacity and version in (None, int(p.name[1:])):
                    found.append((int(p.name[1:]), p, meta))
        if not found:
            raise FileNotFoundError(f"no saved model for region {region!r}, capacity {capacity}"
                                    + (f", version {version}" if version else ""))
        _, path, meta = max(found, key=lambda t: t[0])
        model = joblib.load(path / "model.joblib")
        model.meta = meta
        return model


def fit_for_region(df: pd.DataFrame, capacity: int, train_frac: float = 0.5,
                   all_regions: pd.DataFrame | None = None, **kwargs) -> PrefetchModel:
    """Fit on the warm-up hours only (the same split iter_region uses); never on held-out hours.
    Optional features switch on when the data supports them: weekly with >= 168 h of history,
    cross-region when `all_regions` shares object ids with this region."""
    from .features import hourly_counts, optional_flags
    hours = sorted(df["hour"].unique())
    split = hours[int(len(hours) * train_frac)]
    flags = optional_flags(df if all_regions is None else all_regions, int(split - hours[0]))
    kwargs.setdefault("weekly", flags["weekly"])
    model = PrefetchModel(capacity, **kwargs)
    if flags["cross_region"] and all_regions is not None:
        others = all_regions[all_regions["region"].astype(str) != str(df["region"].iloc[0])]
        model.other = hourly_counts(others)  # summed over the other regions
    return model.fit(df, range(hours[0] + 6, split))
