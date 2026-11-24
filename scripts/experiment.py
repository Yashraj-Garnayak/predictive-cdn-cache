"""Prefetch-model experiments (see docs/superpowers/specs/2026-11-22-prediction-beats-lru-design.md).

  python scripts/experiment.py sample [--estimator hgb|lgbm]   # decisions: CDN-edge-eag hours 0-71 only
  python scripts/experiment.py full --config '{"prefetch_fraction": 0.1, ...}'   # final table, saves models

Sample hours all lie inside the full data's training half, so tuning never touches held-out hours.
"""
from __future__ import annotations
import argparse
import itertools
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from sklearn.model_selection import TimeSeriesSplit
from pcache.features import hourly_counts, static_info
from pcache.policies import HybridCache, LRUCache
from pcache.prefetch_model import PrefetchModel, _estimator, fit_for_region, lru_snapshots, training_set
from pcache.report import precision_at_k
from pcache.simulator import iter_region
from pcache.sources import load_source

META = ("data/requests_hourly.csv", "data/cachemon_titles.csv")
REPORTS = Path("reports")
SAMPLE_REGION, SAMPLE_HOURS, MAIN_CAP = "CDN-edge-eag", 72, 200
GRID = {"max_iter": [100, 300], "learning_rate": [0.05, 0.1], "max_leaf_nodes": [15, 31]}


def sample_df() -> pd.DataFrame:
    df = load_source("meta", *META)
    df = df[(df["region"] == SAMPLE_REGION) & (df["hour"] < SAMPLE_HOURS)]
    return df.assign(region=df["region"].astype(str)).reset_index(drop=True)


def cv_params(df: pd.DataFrame, estimator: str) -> pd.DataFrame:
    """Time-ordered CV on the sample's training hours: always fit on earlier hours, score later ones."""
    hours = sorted(df["hour"].unique())
    split = hours[len(hours) // 2]
    train_hours = np.arange(hours[0] + 6, split)
    snaps = lru_snapshots(df, MAIN_CAP - PrefetchModel(MAIN_CAP).reserved, train_hours)
    counts, static = hourly_counts(df), static_info(df)
    sets = {h: training_set(counts, [h], snaps, static=static) for h in train_hours}
    rows = []
    for values in itertools.product(*GRID.values()):
        params = dict(zip(GRID, values))
        scores = []
        for fit_idx, val_idx in TimeSeriesSplit(n_splits=4).split(train_hours):
            Xf = pd.concat([sets[h][0] for h in train_hours[fit_idx]]); yf = pd.concat([sets[h][1] for h in train_hours[fit_idx]])
            Xv = pd.concat([sets[h][0] for h in train_hours[val_idx]]); yv = pd.concat([sets[h][1] for h in train_hours[val_idx]])
            model = _estimator(estimator, params).fit(Xf, yf > 0)
            scores.append(average_precision_score(yv > 0, model.predict_proba(Xv[list(Xf.columns)])[:, 1]))
        rows.append({"estimator": estimator, **params, "cv_avg_precision": float(np.mean(scores))})
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


def replay(df: pd.DataFrame, capacity: int, model: PrefetchModel | None, full: bool = False) -> dict:
    """Hit rate, byte hit rate and precision for one region; `full` adds LFU/Predictive."""
    policies = None if full else [LRUCache(capacity),
                                  HybridCache(capacity, model.prefetch_fraction if model else 0.10)]
    prec, hitp, last = [], [], None
    for last in iter_region(df, capacity, policies=policies, prefetch_model=model):
        if last.is_test:
            prec.append(precision_at_k(last.predicted, last.actual, 10))
            if last.hit_precision is not None:
                hitp.append(last.hit_precision)
    out = {f"{k}_hit": v * 100 for k, v in last.running_hit_rate.items()}
    out |= {f"{k}_byte": v * 100 for k, v in last.byte_hit_rate.items()}
    out["precision@10"] = float(np.mean(prec))
    out["hit_precision@10"] = float(np.mean(hitp)) if hitp else None
    return out


def sample_job(cfg: dict) -> dict:
    df = sample_df()
    t = time.time()
    model = fit_for_region(df, MAIN_CAP, **cfg)
    res = replay(df, MAIN_CAP, model)
    row = {**cfg, **res, "gap_vs_LRU": res["Hybrid_hit"] - res["LRU_hit"], "seconds": round(time.time() - t)}
    print(row, flush=True)
    return row


def run_sample(estimator: str, workers: int, fractions=(0.05, 0.10, 0.20), tag: str = "") -> None:
    df = sample_df()
    cv = cv_params(df, estimator)
    cv.to_csv(REPORTS / f"sample_cv_{estimator}{tag}.csv", index=False)
    best = cv.sort_values("cv_avg_precision", ascending=False).iloc[0][list(GRID)].to_dict()
    best = {k: (float(v) if k == "learning_rate" else int(v)) for k, v in best.items()}
    sizes = df.drop_duplicates("video_id")["size_bytes"]
    limits = [None, int(sizes.quantile(0.9)), int(sizes.quantile(0.99))]
    cfgs = [{"estimator": estimator, "prefetch_fraction": f, "weighted": w, "max_object_bytes": s, **best}
            for f in fractions for w in (False, True) for s in limits]
    baseline = replay(df, MAIN_CAP, None)  # old Hybrid on the same sample, for reference
    print({"old_hybrid_sample": baseline}, flush=True)
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(sample_job, cfgs))
    out = pd.DataFrame(rows).assign(old_hybrid_gap=baseline["Hybrid_hit"] - baseline["LRU_hit"])
    out.to_csv(REPORTS / f"sample_experiments_{estimator}{tag}.csv", index=False)
    print(out.sort_values("gap_vs_LRU", ascending=False).to_string())


def full_job(job) -> dict:
    region, capacity, cfg = job
    everything = load_source("meta", *META)
    df = everything[everything["region"] == region].assign(region=region).reset_index(drop=True)
    model = fit_for_region(df, capacity, all_regions=everything, **cfg)
    new = replay(df, capacity, model, full=True)
    old = replay(df, capacity, None, full=True)
    path = model.save(Path("models"), region, {"source": "meta", "metrics": new, "config": cfg})
    row = {"region": region, "capacity": capacity,
           "LRU_hit": new["LRU_hit"], "LFU_hit": new["LFU_hit"], "old_Hybrid_hit": old["Hybrid_hit"],
           "new_Hybrid_hit": new["Hybrid_hit"],
           "LRU_byte": new["LRU_byte"], "LFU_byte": new["LFU_byte"], "old_Hybrid_byte": old["Hybrid_byte"],
           "new_Hybrid_byte": new["Hybrid_byte"],
           "old_model_precision@10": old["precision@10"], "new_model_hit_precision@10": new["hit_precision@10"],
           "model": str(path)}
    print(row, flush=True)
    return row


def run_full(cfg: dict, workers: int) -> None:
    jobs = [(r, c, cfg) for c in (200, 50, 1000) for r in ("CDN-edge-eag", "CDN-edge-nha", "CDN-edge-prn")]
    with ProcessPoolExecutor(workers) as ex:
        out = pd.DataFrame(list(ex.map(full_job, jobs)))
    out["new_minus_LRU"] = out["new_Hybrid_hit"] - out["LRU_hit"]
    out.round(3).to_csv(REPORTS / "before_after.csv", index=False)
    print(out.round(2).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sample", "full"])
    ap.add_argument("--estimator", default="hgb")
    ap.add_argument("--config", default="{}")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--fractions", default="0.05,0.1,0.2", help="reserved shares to try on the sample")
    a = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)
    fr = tuple(float(x) for x in a.fractions.split(","))
    run_sample(a.estimator, a.workers, fr, "" if fr == (0.05, 0.1, 0.2) else "_" + a.fractions) if a.mode == "sample" else run_full(json.loads(a.config), a.workers)
