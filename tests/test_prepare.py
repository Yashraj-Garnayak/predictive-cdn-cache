import gzip
import pandas as pd
from scripts.prepare_wikipedia import main, parse_hour, to_requests, to_titles

SAMPLE = b"""de Berlin 50 0
de Special:Search 99 0
en Main_Page 999 0
en Python_(programming_language) 30 0
hi Mumbai 20 0
fr Paris 40 0
broken
en Bad notanumber 0
"""


def test_parse_and_convert():
    df = parse_hour(gzip.compress(SAMPLE), hour=0)
    assert set(df.page) == {"Berlin", "Python_(programming_language)", "Mumbai"}
    req = to_requests(df, top_pages=10, requests_per_hour=100, seed=0)
    assert list(req.columns) == ["region", "hour", "video_id"]
    assert len(req) == 300


def test_titles_match_request_ids(tmp_path):
    df = parse_hour(gzip.compress(SAMPLE), hour=0)
    titles = to_titles(df, top_pages=10)
    assert list(titles.columns) == ["region", "video_id", "title"]
    req = to_requests(df, top_pages=10, requests_per_hour=100, seed=0)
    virginia = titles[titles.region == "Virginia"]
    assert virginia.title.tolist() == ["Python (programming language)"]  # underscores -> spaces
    assert set(req[req.region == "Virginia"].video_id) == set(virginia.video_id)


def test_main_writes_titles_file(tmp_path):
    (tmp_path / "20261101-00.gz").write_bytes(gzip.compress(SAMPLE))  # cached, so no download
    out, titles_out = tmp_path / "req.csv", tmp_path / "titles.csv"
    main(["--hours", "1", "--cache-dir", str(tmp_path), "--out", str(out), "--titles-out", str(titles_out)])
    titles = pd.read_csv(titles_out)
    assert set(titles.title) == {"Berlin", "Python (programming language)", "Mumbai"}
    assert set(titles.region) == set(pd.read_csv(out).region)
