import pandas as pd
import pytest
from pcache.data import load_requests


def test_load_requests_dtypes(tmp_path):
    f = tmp_path / "req.csv"
    pd.DataFrame({"region": ["A", "A", "B"], "hour": [0, 1, 0], "video_id": [5, 6, 5]}).to_csv(f, index=False)
    df = load_requests(f)
    assert list(df.columns) == ["region", "hour", "video_id"]
    assert str(df["region"].dtype) == "category" and str(df["hour"].dtype) == "int32"


def test_load_requests_rejects_folder_and_wrong_csv(tmp_path):
    with pytest.raises(ValueError, match="not a file"):        # e.g. 'data/' typed into the dashboard
        load_requests(tmp_path)
    titles = tmp_path / "cachemon_titles.csv"
    pd.DataFrame({"region": ["A"], "video_id": [1], "title": ["0067"]}).to_csv(titles, index=False)
    with pytest.raises(ValueError, match="not a region,hour,video_id CSV"):
        load_requests(titles)
