import pandas as pd
from pcache.data import generate_requests
from pcache.report import build_report, precision_at_k, mean_abs_error


def test_metric_helpers():
    pred = pd.Series({1: 9.0, 2: 5.0, 3: 1.0})
    actual = pd.Series({1: 10, 3: 6, 4: 2})
    assert precision_at_k(pred, actual, k=2) == 0.5          # only video 1 in both top-2s
    assert mean_abs_error(pred, actual) == (1 + 5 + 5 + 2) / 4  # video 4 counted as predicted 0


def test_build_report(tmp_path):
    df = generate_requests(regions=("A",), hours=24, n_videos=2000, requests_per_hour=300)
    metrics = build_report(df, capacity=50, out=tmp_path)
    assert (tmp_path / "metrics.csv").exists()
    assert (tmp_path / "hit_rate_a.png").stat().st_size > 0
    assert (tmp_path / "pred_vs_actual_a.png").stat().st_size > 0
    names = set(metrics["name"])
    assert {"LRU", "LFU", "Predictive", "Hybrid", "precision@10", "mean_abs_error"} <= names
    assert {f"predicted_rank_{i}" for i in range(1, 11)} <= names
