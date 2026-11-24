"""Read pre-aggregated hourly counts from PostgreSQL (table requests_hourly) and object titles (table titles).

Connection details come only from the environment (PGHOST, PGPORT, PGDATABASE, PGUSER,
PGPASSWORD, PGSSLMODE), which libpq reads itself; nothing is stored in code or config.
"""
from __future__ import annotations
import os
import pandas as pd
import psycopg

REQUIRED_ENV = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")
COLUMNS = ["region", "hour", "video_id", "requests"]


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    """Run one query; raise ValueError with a readable message on any setup or database error."""
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        raise ValueError(f"Set the environment variable(s) {', '.join(missing)} (see .env.example)")
    try:
        with psycopg.connect(sslmode=os.environ.get("PGSSLMODE", "require"), connect_timeout=10) as conn:
            return conn.execute(sql, params).fetchall()
    except psycopg.Error as e:
        raise ValueError(f"Database error: {str(e).strip()}") from e


def regions() -> list[str]:
    return [r for (r,) in _query("SELECT DISTINCT region FROM requests_hourly ORDER BY region")]


def load_region(region: str) -> pd.DataFrame:
    """One region's hourly counts (region, hour, video_id, requests), never the whole table."""
    rows = _query("SELECT region, hour, video_id, requests FROM requests_hourly "
                  "WHERE region = %s ORDER BY hour, video_id", (region,))
    return pd.DataFrame(rows, columns=COLUMNS).astype(
        {"region": "category", "hour": "int32", "video_id": "int32", "requests": "int64"})


def load_titles(region: str) -> pd.DataFrame:
    """One region's object names, content types and sizes (table titles)."""
    rows = _query("SELECT video_id, title, content_type, size_bytes FROM titles WHERE region = %s", (region,))
    return pd.DataFrame(rows, columns=["video_id", "title", "content_type", "size_bytes"]).astype(
        {"video_id": "int64", "content_type": "Int64", "size_bytes": "Float64"})  # NULL stays NULL, ints stay ints
