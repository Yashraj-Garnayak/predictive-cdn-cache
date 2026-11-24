import pandas as pd
from pcache.features import hourly_counts
from pcache.prefetch_model import lru_snapshots, training_set


def hourly(rows):
    return pd.DataFrame(rows, columns=["region", "hour", "video_id", "requests"])


def test_snapshot_is_start_of_hour():
    df = hourly([("A", 0, 1, 1), ("A", 1, 2, 1)])
    snaps = lru_snapshots(df, 1, [0, 1])
    assert snaps[0] == frozenset() and snaps[1] == frozenset({1})


def test_training_set_excludes_cached_and_labels():
    # video 1 every hour (stays cached); video 2 only at hours 2 and 7 (evicted in between at capacity 1)
    rows = [("A", h, 1, 1) for h in range(8)] + [("A", 2, 2, 1), ("A", 7, 2, 1)]
    df = hourly(rows)
    counts = hourly_counts(df)
    snaps = lru_snapshots(df, 1, range(8))
    X, y = training_set(counts, [7], snaps)
    assert 1 not in X.index          # cached at the start of hour 7
    assert y.loc[2] > 0              # requested at hour 7 while not cached


def test_training_set_empty_hour():
    df = hourly([("A", h, 1, 1) for h in range(8)])
    counts = hourly_counts(df)
    X, y = training_set(counts, [7], lru_snapshots(df, 5, range(8)))
    assert X.empty and y.empty


def test_snapshots_no_hours():
    assert lru_snapshots(hourly([("A", 0, 1, 1)]), 1, []) == {}


# ---------- PrefetchModel ----------
import math
import pytest
from pcache.data import generate_requests
from pcache.prefetch_model import PrefetchModel, fit_for_region
from pcache.simulator import iter_region


def region_df(hours=24, sizes=False):
    df = generate_requests(regions=("A",), hours=hours, n_videos=2000, requests_per_hour=300)
    df = df.groupby(["region", "hour", "video_id"]).size().rename("requests").reset_index()
    return df.assign(size_bytes=df["video_id"] + 1, content_type=df["video_id"] % 3) if sizes else df


@pytest.fixture(scope="module")
def fitted():
    df = region_df(sizes=True)
    return df, fit_for_region(df, 50)


def test_save_load_versions(tmp_path, fitted):
    _, m = fitted
    assert m.save(tmp_path, "A", {"note": 1}).name == "v1"
    assert m.save(tmp_path, "A", {"note": 2}).name == "v2"
    assert PrefetchModel.load(tmp_path, "A", 50).meta["note"] == 2
    assert PrefetchModel.load(tmp_path, "A", 50, version=1).meta["note"] == 1


def test_load_wrong_capacity_raises(tmp_path, fitted):
    fitted[1].save(tmp_path, "A", {})
    with pytest.raises(FileNotFoundError):
        PrefetchModel.load(tmp_path, "A", 200)


def test_model_never_sees_test_hours(monkeypatch):
    import pcache.prefetch_model as pm
    seen = []
    real = pm.training_set
    monkeypatch.setattr(pm, "training_set", lambda counts, hours, *a, **k: (seen.extend(hours), real(counts, hours, *a, **k))[1])
    df = region_df()
    fit_for_region(df, 50)
    split = sorted(df["hour"].unique())[len(df["hour"].unique()) // 2]
    assert seen and max(seen) < split


def test_iter_region_with_prefetch_model_runs(fitted):
    df, m = fitted
    steps = list(iter_region(df, 50, prefetch_model=m))
    test = [s for s in steps if s.is_test]
    assert all(math.isfinite(v) for v in steps[-1].running_hit_rate.values())
    assert all(0 <= s.hit_precision <= 1 for s in test)
    assert all(s.hit_precision is None for s in steps if not s.is_test)


def test_rank_skips_large_objects(fitted):
    df, m = fitted
    from pcache.features import hourly_counts
    counts = hourly_counts(df)
    static = df.drop_duplicates("video_id").set_index("video_id")[["size_bytes", "content_type"]]
    m.max_object_bytes = 10
    try:
        ranked = m.rank(counts, 20, exclude=set(), static=static)
    finally:
        m.max_object_bytes = None
    assert ranked and all(static.loc[k, "size_bytes"] <= 10 for k in ranked)


def test_capacity_mismatch_raises(fitted):
    df, m = fitted
    with pytest.raises(ValueError, match="capacity"):
        next(iter_region(df, 200, prefetch_model=m))


def test_save_skips_version_taken_meanwhile(tmp_path, fitted, monkeypatch):
    from pathlib import Path
    real_mkdir = Path.mkdir
    def racing_mkdir(self, *a, **k):  # another process creates v1 between the scan and our mkdir
        if self.name == "v1" and not self.exists():
            real_mkdir(self, parents=True)
        return real_mkdir(self, *a, **k)
    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    assert fitted[1].save(tmp_path, "A", {}).name == "v2"


def test_fit_for_region_switches_on_optional_features():
    long = region_df(hours=400)
    assert fit_for_region(long, 50).weekly is True
    two = pd.concat([region_df(), region_df().assign(region="B")])
    m = fit_for_region(two[two["region"] == "A"], 50, all_regions=two)
    assert m.other is not None and "other_regions_recent" in m.features
    assert fit_for_region(region_df(), 50).other is None
