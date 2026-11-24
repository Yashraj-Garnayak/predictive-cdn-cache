# Adding a data source

Every source is turned into one standard table before the simulator sees it
(`src/pcache/sources.py`).

| column | required | meaning |
|---|---|---|
| `region` | yes | cache location (one simulation per region) |
| `hour` | yes | whole number ≥ 0, hours since the trace start |
| `object_id` | yes | integer id of the object; **the same object must have the same id in every region** |
| `requests` | yes | requests for that object in that hour, > 0 |
| `size_bytes` | no | object size; enables byte hit rate and the size limit on prefetch |
| `content_type` | no | numeric content-type code; used as a model feature |

There is one row per (region, hour, object_id). `validate()` rejects missing columns, duplicate
rows, bad hours (negative, fractional or empty) and requests ≤ 0. Its error message names the
problem.

## Steps

1. Write a function that reads your raw files and returns a frame with the columns above.
   It ends with `return validate(df)`:

   ```python
   def my_logs(path) -> pd.DataFrame:
       raw = pd.read_csv(path)  # e.g. timestamp, pop, url, bytes
       raw["hour"] = (pd.to_datetime(raw["timestamp"]) - pd.Timestamp("2026-01-01")) // pd.Timedelta("1h")
       raw["object_id"] = pd.factorize(raw["url"])[0]  # factorize over ALL regions at once
       df = (raw.groupby(["pop", "hour", "object_id"])
                .agg(requests=("url", "size"), size_bytes=("bytes", "max"))
                .reset_index().rename(columns={"pop": "region"}))
       return validate(df)
   ```

2. Register it in `ADAPTERS`: `ADAPTERS["my_logs"] = my_logs`.
3. Load it with `load_source("my_logs", "path/to/file.csv")`.
4. Add a small test next to the existing ones in `tests/test_sources.py`.

## What switches on automatically
- **Cross-region feature:** turns on when some `object_id` appears in two or more regions. That is
  why ids must be shared across regions: if each region numbers its objects from 0, regions look
  like they share objects they don't.
- **Weekly features** (lag 168 h, day of week): turn on when the training hours cover at least
  168 hours.
- **Byte hit rate and the size limit:** need `size_bytes`.

Sources included: `meta` (Meta CDN traces, with sizes), `wikipedia` (pageviews) and `hourly_csv`
(a file already in the standard format).
