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
