"""Database source, tested against an in-memory SQLite stand-in for PostgreSQL (same SQL, %s -> ?)."""
import ast
import sqlite3
from pathlib import Path
import pandas as pd
import psycopg
import pytest
from pcache import db
from pcache.data import CSV_DTYPES, generate_requests
from pcache.features import hourly_counts
from pcache.simulator import iter_region

ENV = {"PGHOST": "db.example", "PGDATABASE": "cdn", "PGUSER": "u", "PGPASSWORD": "p"}


def requests_df():
    return generate_requests(regions=("A", "B"), hours=24, n_videos=2000, requests_per_hour=300)


def to_hourly(df):
    return df.groupby(["region", "hour", "video_id"]).size().rename("requests").reset_index()


class FakePG:
    def __init__(self, conn, log):
        self.conn, self.log = conn, log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.log.append((sql, params))
        return self.conn.execute(sql.replace("%s", "?"), params)


@pytest.fixture
def fake_db(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    to_hourly(requests_df()).to_sql("requests_hourly", conn, index=False)
    pd.DataFrame({"region": ["A", "A", "A", "B"], "video_id": [1, 2, 3, 1],
                  "title": ["Cats", "Dogs", None, "Other"], "content_type": [4, 3, None, 4],
                  "size_bytes": [21000, 0, None, 5]}).to_sql("titles", conn, index=False)
    log, kwargs = [], []
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("PGSSLMODE", raising=False)
    monkeypatch.setattr(psycopg, "connect", lambda **kw: kwargs.append(kw) or FakePG(conn, log))
    return log, kwargs


def test_load_region_queries_only_that_region(fake_db):
    log, kwargs = fake_db
    assert db.regions() == ["A", "B"]
    df = db.load_region("B")
    assert list(df.columns) == db.COLUMNS and set(df["region"]) == {"B"}
    assert "WHERE region = %s" in log[-1][0] and log[-1][1] == ("B",)
    assert kwargs[-1]["sslmode"] == "require"
    pd.testing.assert_frame_equal(hourly_counts(df), hourly_counts(requests_df().astype(CSV_DTYPES).query("region == 'B'")))


def test_missing_env_and_db_errors_are_readable(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError, match="PGHOST, PGDATABASE, PGUSER, PGPASSWORD"):
        db.regions()
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

    def refuse(**kw):
        raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(psycopg, "connect", refuse)
    with pytest.raises(ValueError, match="Database error: connection refused"):
        db.regions()


def test_hourly_counts_replay_matches_request_rows():
    raw = requests_df().query("region == 'A'")
    hourly = to_hourly(raw)  # sorted by (hour, video_id): a back-to-back replay would inflate hit rates
    for a, b in zip(iter_region(hourly, 50), iter_region(raw, 50), strict=True):
        pd.testing.assert_series_equal(a.actual, b.actual)
        if a.predicted is not None:
            pd.testing.assert_series_equal(a.predicted, b.predicted)
    for name in a.running_hit_rate:  # same traffic in a different random order: close, not inflated
        assert abs(a.running_hit_rate[name] - b.running_hit_rate[name]) < 0.05, name


def test_load_titles_returns_only_that_region(fake_db):
    log, _ = fake_db
    df = db.load_titles("A")
    assert list(df.columns) == ["video_id", "title", "content_type", "size_bytes"]
    assert sorted(df["title"].dropna()) == ["Cats", "Dogs"]
    assert "WHERE region = %s" in log[-1][0] and log[-1][1] == ("A",)


def test_every_query_uses_a_literal_sql_string_and_params():
    calls = [n for n in ast.walk(ast.parse(Path(db.__file__).read_text()))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_query"]
    assert len(calls) >= 3
    for c in calls:
        sql = c.args[0]
        assert isinstance(sql, ast.Constant) and isinstance(sql.value, str)   # no f-string, %, + or .format
        if "region = %s" in sql.value:
            assert len(c.args) == 2 and isinstance(c.args[1], ast.Tuple)
