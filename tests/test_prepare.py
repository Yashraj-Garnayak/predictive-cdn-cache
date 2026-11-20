import gzip
from scripts.prepare_wikipedia import parse_hour, to_requests

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
