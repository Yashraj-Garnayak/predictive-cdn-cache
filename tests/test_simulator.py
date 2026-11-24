from pcache.data import generate_requests
from pcache.simulator import simulate, simulate_region, iter_region


def small_df():
    return generate_requests(regions=("A",), hours=24, n_videos=2000, requests_per_hour=300)


def test_end_to_end_small():
    res = simulate(small_df(), capacity=50)
    assert set(res.columns) == {"LRU", "LFU", "Predictive", "Hybrid"}
    assert ((res >= 0) & (res <= 100)).all().all()


def test_iter_region_yields_each_hour():
    df = small_df()
    steps = list(iter_region(df, capacity=50))
    assert [s.hour for s in steps] == list(range(24))
    assert [s.is_test for s in steps] == [False] * 12 + [True] * 12
    assert all(s.predicted is None for s in steps[:12])
    assert all(len(s.predicted) > 0 for s in steps[12:])
    assert all(0 <= v <= 1 for s in steps for v in s.hourly_hit_rate.values())
    assert steps[-1].running_hit_rate == simulate_region(df, capacity=50)


def test_features_include_hour_of_day_and_lag_24():
    from pcache.features import FEATURES, build_features, hourly_counts
    counts = hourly_counts(small_df())
    f = build_features(counts, 24)  # lag_24 looks back to hour 0
    assert {"hour_of_day", "lag_24"} <= set(FEATURES) <= set(f.columns)
    assert (f["hour_of_day"] == 0).all() and (f["lag_24"] > 0).any()


def hourly_df(sizes=False):
    df = small_df().groupby(["region", "hour", "video_id"]).size().rename("requests").reset_index()
    return df.assign(size_bytes=df["video_id"] * 10 + 1) if sizes else df


def test_unknown_size_counts_zero():
    steps = list(iter_region(hourly_df(), capacity=50))
    assert all(v == 0.0 for s in steps for v in s.byte_hit_rate.values())


def test_byte_hit_rate_with_sizes():
    last = list(iter_region(hourly_df(sizes=True), capacity=50))[-1]
    assert set(last.byte_hit_rate) == set(last.running_hit_rate)
    assert all(0 < v < 1 for v in last.byte_hit_rate.values())


def test_seed_changes_order_not_totals():
    a = list(iter_region(hourly_df(), 50, seed=0))
    b = list(iter_region(hourly_df(), 50, seed=1))
    assert all(x.actual.equals(y.actual) for x, y in zip(a, b))
    assert a[-1].running_hit_rate != b[-1].running_hit_rate
    assert all(abs(a[-1].running_hit_rate[k] - b[-1].running_hit_rate[k]) < 0.05 for k in a[-1].running_hit_rate)


def test_nan_size_counts_zero():
    df = hourly_df(sizes=True)
    df.loc[df["video_id"] == df["video_id"].iloc[0], "size_bytes"] = float("nan")
    last = list(iter_region(df, capacity=50))[-1]
    assert all(0 < v < 1 for v in last.byte_hit_rate.values())
