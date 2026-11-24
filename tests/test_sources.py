import numpy as np
import pandas as pd
import pytest
from pcache.sources import load_source, validate


def frame(**over):
    d = {"region": ["A", "A"], "hour": [0, 1], "object_id": [1, 1], "requests": [3, 4]}
    d.update(over)
    return pd.DataFrame(d)


def test_validate_rejects_missing_column():
    with pytest.raises(ValueError, match="object_id"):
        validate(frame().drop(columns="object_id"))


def test_validate_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate"):
        validate(frame(hour=[0, 0]))


@pytest.mark.parametrize("bad", [-1, 1.5, np.nan])
def test_validate_rejects_bad_hours(bad):
    with pytest.raises(ValueError, match="hour"):
        validate(frame(hour=[0, bad]))


def test_validate_rejects_nonpositive_requests():
    with pytest.raises(ValueError, match="requests"):
        validate(frame(requests=[3, 0]))


def test_validate_returns_compact_dtypes():
    df = validate(frame())
    assert str(df["region"].dtype) == "category" and str(df["hour"].dtype) == "int32"


def meta_files(tmp_path):
    req = tmp_path / "req.csv"
    titles = tmp_path / "titles.csv"
    pd.DataFrame({"region": ["A", "B"], "hour": [0, 0], "video_id": [0, 7], "requests": [2, 5]}).to_csv(req, index=False)
    pd.DataFrame({"region": ["A", "B"], "video_id": [0, 7], "title": ["x", "x"],
                  "content_type": [4, 4], "size_bytes": [100, 100]}).to_csv(titles, index=False)
    return req, titles


def test_meta_adapter_shared_ids_and_sizes(tmp_path):
    from pcache.sources import ADAPTERS
    df = ADAPTERS["meta"](*meta_files(tmp_path))
    assert df["object_id"].nunique() == 1          # same title in A and B -> one id
    assert df["size_bytes"].tolist() == [100, 100]


def test_wikipedia_adapter_aggregates(tmp_path):
    from pcache.sources import ADAPTERS
    req, titles = tmp_path / "w.csv", tmp_path / "wt.csv"
    pd.DataFrame({"region": ["A"] * 3, "hour": [0] * 3, "video_id": [5] * 3}).to_csv(req, index=False)
    pd.DataFrame({"region": ["A"], "video_id": [5], "title": ["Page"]}).to_csv(titles, index=False)
    df = ADAPTERS["wikipedia"](req, titles)
    assert df["requests"].tolist() == [3]


def test_load_source_returns_internal_columns(tmp_path):
    df = load_source("meta", *meta_files(tmp_path))
    assert "video_id" in df and "object_id" not in df


def test_validate_rejects_fractional_requests():
    with pytest.raises(ValueError, match="requests"):
        validate(frame(requests=[3, 2.7]))


def test_validate_rejects_bad_object_id_and_size():
    with pytest.raises(ValueError, match="object_id"):
        validate(frame(object_id=[1, np.nan]))
    with pytest.raises(ValueError, match="size_bytes"):
        validate(frame().assign(size_bytes=[10, -1]))


def test_meta_adapter_rejects_blank_titles(tmp_path):
    from pcache.sources import ADAPTERS
    req, titles = meta_files(tmp_path)
    t = pd.read_csv(titles); t["title"] = ["", ""]; t.to_csv(titles, index=False)
    with pytest.raises(ValueError, match="title"):
        ADAPTERS["meta"](req, titles)
