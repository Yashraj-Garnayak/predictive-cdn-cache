import numpy as np
import pandas as pd
from pcache.data import generate_requests
from pcache.features import hourly_counts, optional_flags, rich_features


def counts():
    return hourly_counts(generate_requests(regions=("A",), hours=30, n_videos=500, requests_per_hour=200))


def test_rich_features_only_past():
    c = counts()
    before = rich_features(c, 10)
    future = c.copy()
    future.loc[10:] = np.random.default_rng(1).integers(0, 50, future.loc[10:].shape)
    pd.testing.assert_frame_equal(before, rich_features(future, 10))


def test_rich_features_columns():
    f = rich_features(counts(), 26)
    assert {"lag_1", "lag_24", "growth", "ewm_6", "hours_since_first_seen", "hour_of_day"} <= set(f.columns)
    assert "lag_168" not in f and "day_of_week" not in f and "size_bytes" not in f


def test_hours_since_first_seen():
    c = pd.DataFrame({7: [0, 0, 0, 2, 0, 1, 0, 0, 0, 0]}, index=range(10))
    assert rich_features(c, 8).loc[7, "hours_since_first_seen"] == 5


def test_static_and_cross_region_columns():
    c = counts()
    static = pd.DataFrame({"size_bytes": 10, "content_type": 3}, index=c.columns)
    other = c * 2
    f = rich_features(c, 12, static=static, other=other)
    assert (f["size_bytes"] == 10).all()
    assert (f["other_regions_recent"] == 2 * c.loc[6:11].sum().reindex(f.index)).all()


def test_weekly_off_for_short_history():
    df = pd.DataFrame({"region": ["A", "B"], "hour": [0, 0], "video_id": [1, 2]})
    assert optional_flags(df, 100) == {"weekly": False, "cross_region": False}
    assert optional_flags(df, 168)["weekly"] is True


def test_cross_region_flag():
    df = pd.DataFrame({"region": ["A", "B"], "hour": [0, 0], "video_id": [1, 1]})
    assert optional_flags(df, 10)["cross_region"] is True


def test_weekly_columns_when_on():
    c = hourly_counts(generate_requests(regions=("A",), hours=180, n_videos=300, requests_per_hour=100))
    f = rich_features(c, 175, weekly=True)
    assert (f["lag_168"] == c.loc[7].reindex(f.index)).all()
    assert (f["day_of_week"] == (175 // 24) % 7).all()
