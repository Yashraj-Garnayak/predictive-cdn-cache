"""Metrics and PNG charts comparing cache policies and the popularity model."""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd
from .simulator import POLICY_NAMES, iter_region

log = logging.getLogger(__name__)


def align(predicted: pd.Series, actual: pd.Series) -> pd.DataFrame:
    """Predicted vs actual count per video; videos the model skipped count as predicted 0."""
    idx = predicted.index.union(actual[actual > 0].index)
    return pd.DataFrame({"predicted": predicted.reindex(idx, fill_value=0.0),
                         "actual": actual.reindex(idx, fill_value=0)})


def precision_at_k(predicted: pd.Series, actual: pd.Series, k: int = 10) -> float:
    """Share of the predicted top-k videos that really were in the actual top-k."""
    pred_top = set(predicted.nlargest(k).index)
    if not pred_top:
        return 0.0
    return len(pred_top & set(actual.nlargest(k).index)) / k


def mean_abs_error(predicted: pd.Series, actual: pd.Series) -> float:
    a = align(predicted, actual)
    return float((a["predicted"] - a["actual"]).abs().mean())


def top_k_table(predicted: pd.Series, actual: pd.Series, k: int = 10) -> pd.DataFrame:
    """Side-by-side ranking of the model's top-k and the real top-k videos."""
    p, a = predicted.nlargest(k), actual.nlargest(k)
    return pd.DataFrame({
        "rank": range(1, k + 1),
        "predicted_video": [int(v) for v in p.index],
        "predicted_count": p.round(1).to_numpy(),
        "actual_video": [int(v) for v in a.index],
        "actual_count": a.to_numpy(),
    })


def region_results(df: pd.DataFrame, capacity: int, k: int = 10) -> dict:
    """Run one region and collect everything the report needs."""
    hourly, quality, scatter, tables, last = [], [], [], {}, None
    for r in iter_region(df, capacity):
        hourly.append({"hour": r.hour, "is_test": r.is_test, **r.hourly_hit_rate})
        if r.is_test:
            quality.append({"hour": r.hour, "precision": precision_at_k(r.predicted, r.actual, k),
                            "mae": mean_abs_error(r.predicted, r.actual)})
            scatter.append(align(r.predicted, r.actual).assign(hour=r.hour))
            tables[r.hour] = top_k_table(r.predicted, r.actual, k)
        last = r
    sample_hour = list(tables)[len(tables) // 2]  # a test hour from the middle of the period
    return {
        "hourly": pd.DataFrame(hourly).set_index("hour"),
        "quality": pd.DataFrame(quality).set_index("hour"),
        "scatter": pd.concat(scatter),
        "final": last.running_hit_rate,
        "sample_hour": sample_hour,
        "sample_table": tables[sample_hour],
    }


def plot_hit_rate(hourly: pd.DataFrame, region: str, path: Path) -> None:
    from matplotlib.figure import Figure  # only reports need matplotlib; the API image leaves it out
    fig = Figure(figsize=(10, 4.5))
    ax = fig.subplots()
    for name in POLICY_NAMES:
        ax.plot(hourly.index, hourly[name] * 100, label=name, marker=".")
    warm = hourly.index[~hourly["is_test"]]
    if len(warm):
        ax.axvspan(warm.min(), warm.max() + 0.5, color="grey", alpha=0.15, label="warm-up\n(model training)")
    ax.set(title=f"{region}: cache hit rate per hour", xlabel="hour", ylabel="hit rate (%)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def plot_pred_vs_actual(scatter: pd.DataFrame, region: str, path: Path) -> None:
    from matplotlib.figure import Figure  # only reports need matplotlib; the API image leaves it out
    fig = Figure(figsize=(5.5, 5.5))
    ax = fig.subplots()
    ax.scatter(scatter["actual"], scatter["predicted"], s=4, alpha=0.25)
    hi = max(scatter["actual"].max(), scatter["predicted"].max()) * 1.05
    ax.plot([0, hi], [0, hi], color="red", lw=1, label="perfect prediction")
    ax.set(title=f"{region}: predicted vs actual requests\n(one dot = one video in one test hour)",
           xlabel="actual requests", ylabel="predicted requests", xlim=(0, hi), ylim=(0, hi))
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def build_report(df: pd.DataFrame, capacity: int, out: Path, k: int = 10) -> pd.DataFrame:
    """Write charts and metrics.csv to `out`; return the metrics table."""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for region, g in df.groupby("region"):
        log.info("reporting %s", region)
        res = region_results(g, capacity, k)
        slug = str(region).lower().replace(" ", "_")
        plot_hit_rate(res["hourly"], region, out / f"hit_rate_{slug}.png")
        plot_pred_vs_actual(res["scatter"], region, out / f"pred_vs_actual_{slug}.png")
        for name, rate in res["final"].items():
            rows.append((region, "hit_rate_pct", name, round(rate * 100, 2)))
        rows.append((region, "prediction", f"precision@{k}", round(res["quality"]["precision"].mean(), 4)))
        rows.append((region, "prediction", "mean_abs_error", round(res["quality"]["mae"].mean(), 4)))
        rows.append((region, "top_sample", "sample_hour", res["sample_hour"]))
        for t in res["sample_table"].itertuples():
            rows.append((region, "top_sample", f"predicted_rank_{t.rank}", t.predicted_video))
            rows.append((region, "top_sample", f"actual_rank_{t.rank}", t.actual_video))
    # object dtype keeps video ids / hours as integers next to the float metrics
    metrics = pd.DataFrame(rows, columns=["region", "section", "name", "value"], dtype=object)
    metrics.to_csv(out / "metrics.csv", index=False)
    return metrics
