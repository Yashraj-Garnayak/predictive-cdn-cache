# Prediction Beats LRU: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the new Hybrid beat LRU on held-out hours (cache size 200, every region, above
replay noise). Add a standard data format with an adapter per source.

**Architecture:**
- The old count model stays as it is and keeps feeding Predictive, the API and the dashboard.
- A new classifier (`PrefetchModel`) is trained on "requested this hour and not in LRU at the
  start of the hour". It feeds only Hybrid's reserved share, when passed to `iter_region`.
- Data enters through `sources.py`. Its adapters produce one validated standard frame.

**Tech Stack:** Python 3.11+, pandas, scikit-learn (HistGradientBoostingClassifier), joblib, pytest.
LightGBM is tried in a scratch venv only, and added to `pyproject.toml` only if it wins.

**Spec:** `docs/superpowers/specs/2026-11-22-prediction-beats-lru-design.md`

## Global Constraints
- Keep rule: the new Hybrid must beat LRU at capacity 200 in every region by more than replay
  noise (at least 0.2 points). Report capacities 50 and 1000 as well.
- Train on hours < split only (split = hours[len(hours) // 2]). Tune on the sample (hours 0–71 of
  `CDN-edge-eag`) only. Use the full held-out hours once, for the final table.
- No commits. Every "commit" step in this plan is replaced by running the tests.
- No new dependency unless LightGBM wins.
- The API, dashboard, `POLICY_NAMES` and `iter_region`'s existing parameters keep working
  unchanged.

## Review Focus
1. Duplicate (region, hour, object_id) rows from a source should be rejected, not silently summed.
   Tested in Task 1.
2. An object with no known size should count as 0 bytes, not crash byte hit rate. Tested in
   Task 2.
3. An hour with no candidates outside LRU should give Hybrid an empty prefetch, not an error.
   Tested in Task 4.
4. A source with fewer than 168 hours of history must not produce lag-168 or day-of-week columns.
   Tested in Task 3.
5. Loading a model saved for a different capacity must not return it silently. Tested in Task 5.

---

### Task 0: Baseline (already running)
- [x] `scratchpad/baseline.py` runs the current code on `data/requests_hourly.csv` at capacities
  200, 50 and 1000 and writes `reports/baseline.csv` (LRU, LFU, Predictive, Hybrid, precision@10).
- [ ] Afterwards: measure replay noise by running capacity 200 with seeds 1 and 2 (Task 2 adds
  `seed`). Noise = the largest change in (Hybrid − LRU) across seeds. Threshold =
  max(0.2, noise).

### Task 1: Standard format, validation, adapters, docs
**Files:** Create `src/pcache/sources.py`, `docs/data-sources.md`, `tests/test_sources.py`.

**Interfaces (produces):**
- `STANDARD = ["region", "hour", "object_id", "requests"]`, `OPTIONAL = ["size_bytes", "content_type"]`
- `validate(df: pd.DataFrame) -> pd.DataFrame` checks the frame and raises `ValueError` naming the
  problem:
  - missing columns;
  - a duplicate (region, hour, object_id);
  - an hour that is NaN, negative or not a whole number;
  - requests ≤ 0.

  It returns the frame with dtypes region=category, hour=int32, object_id=int64, requests=int64.
- `ADAPTERS: dict[str, Callable[..., pd.DataFrame]]` with `"hourly_csv"(path)`, `"meta"(requests_path, titles_path)`
  and `"wikipedia"(requests_path, titles_path)`. Each returns `validate(...)` output.
  - meta and wikipedia map each object's `title` to one id shared by all regions
    (`pd.factorize` over the titles).
  - wikipedia aggregates one-row-per-request input into `requests`.
  - meta joins `size_bytes` and `content_type`.
- `load_source(name: str, *paths) -> pd.DataFrame` runs `ADAPTERS[name](*paths)` and then
  renames `object_id` to `video_id`. The rename is commented
  `# shortcut: internal code still says video_id, rename internals if a second id kind appears`.

- [ ] **Step 1: Write the failing tests** in `tests/test_sources.py`:
  - `test_validate_rejects_missing_column`: match `"object_id"`.
  - `test_validate_rejects_duplicates`: two rows of (A, 0, 1). Match `"duplicate"`.
  - `test_validate_rejects_bad_hours`: one test each for hour -1, 1.5 and NaN. Match `"hour"`.
  - `test_validate_rejects_nonpositive_requests`: requests 0. Match `"requests"`.
  - `test_meta_adapter_shared_ids_and_sizes`: tiny CSVs in `tmp_path`, where title `"x"` is in
    regions A and B with different per-region ids. Assert it gets one `object_id` in both
    regions, and that `size_bytes` is carried over.
  - `test_wikipedia_adapter_aggregates`: 3 request rows for one (region, hour, video) become
    `requests == 3`.
  - `test_load_source_returns_internal_columns`: `"video_id" in df` and `"object_id" not in df`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_sources.py -v`. Expect it to FAIL
  with `ModuleNotFoundError: pcache.sources`.
- [ ] **Step 3:** Implement `sources.py` with the interfaces above.
- [ ] **Step 4:** Rerun the command. Expect all tests to PASS.
- [ ] **Step 5:** Write `docs/data-sources.md`. It covers the standard columns and their rules,
  a 10-line adapter example, how to register it in `ADAPTERS`, and the rule that `object_id`
  must mean the same object in every region. Link it from `README.md`.

### Task 2: Byte hit rate and replay seed
**Files:** Modify `src/pcache/policies.py` and `src/pcache/simulator.py`. Tests go in
`tests/test_policies.py` and `tests/test_simulator.py`.

**Interfaces (produces):**
- `CachePolicy.request(key: int, size: int = 0) -> bool`. It also adds to `bytes_requested`,
  and to `bytes_hit` on a hit.
- `CachePolicy.byte_hit_rate -> float`, which returns 0.0 when no bytes have been requested.
- `HourResult.byte_hit_rate: dict[str, float]` (running, same phase rules as `running_hit_rate`).
  The field is added last and defaults to an empty dict.
- `iter_region(..., seed: int = 0)`: the size of each object comes from the `size_bytes` column
  when present, and is 0 otherwise (or for an unknown object).
- `hour_requests(group: pd.DataFrame, rng) -> np.ndarray` holds the replay order. Both
  `iter_region` and Task 4 use it, so the two replays match.
- When the warm-up ends, `bytes_hit` and `bytes_requested` are reset along with hits and
  requests.

- [ ] **Step 1: Write the failing tests:**
  - `test_byte_hit_rate_counts_sizes`: on an LRU of size 2, request (1, 100), (1, 100), (2, 900).
    Assert the byte hit rate is 100/1100.
  - `test_unknown_size_counts_zero`: on a frame without `size_bytes`, `iter_region` runs and every
    `byte_hit_rate` value is 0.0.
  - `test_seed_changes_order_not_totals`: hourly frame, seeds 0 and 1. The `actual` series are
    equal and the hit rates differ by less than 0.05.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_policies.py tests/test_simulator.py -v`.
  Expect it to FAIL.
- [ ] **Step 3:** Implement. Hybrid and Predictive pass `size` through to their LRU parts.
- [ ] **Step 4:** Run the full suite with `.venv/bin/python -m pytest -q`. Expect all tests to
  pass, with the API tests unchanged.

### Task 3: Rich features (with optional weekly and cross-region features)
**Files:** Modify `src/pcache/features.py`. Tests go in `tests/test_features.py` (create it).

**Interfaces (produces):**
- `rich_features(counts, hour, *, static=None, other=None, weekly=False) -> pd.DataFrame`. It uses
  only hours < `hour`, and has one row per candidate (same candidate rule as `build_features`).
- Columns:
  - `lag_1, lag_2, lag_3, lag_6, lag_24, growth, ewm_6, hours_since_first_seen, hour_of_day`;
  - plus `size_bytes` and `content_type` (an integer code) when `static` (a frame indexed by
    video_id) is given;
  - plus `lag_168` and `day_of_week` when `weekly`;
  - plus `other_regions_recent` (the sum over the other regions of the last 6 hours) when
    `other` is given. `other` is another counts matrix, summed across the other regions.
- `optional_flags(df_all_regions: pd.DataFrame, train_hours: int) -> dict` returns
  `{"weekly": train_hours >= 168, "cross_region": <any video_id in ≥2 regions>}`.
- `build_features` and `FEATURES` are unchanged, so the old model is untouched.

- [ ] **Step 1: Write the failing tests:**
  - `test_rich_features_only_past`: build features at h=10 on counts, change every row ≥ 10 to
    random values, rebuild, and assert the frames are equal. This is the leakage test for
    features.
  - `test_hours_since_first_seen`: an object first seen at hour 3, with features at hour 8,
    gives 5.
  - `test_weekly_off_for_short_history`: `optional_flags` on 100 training hours gives
    `weekly=False`, and `rich_features(..., weekly=False)` has no `lag_168` column.
  - `test_cross_region_flag`: the flag is False on frames with no shared ids and True when one
    id appears in 2 regions.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_features.py -v`. Expect it to FAIL.
- [ ] **Step 3:** Implement. Use `ewm_6` = `counts.loc[:hour-1].ewm(span=6).mean().iloc[-1]`, with
  `hours_since_first_seen` taken from the first nonzero index per column.
- [ ] **Step 4:** Rerun the command. Expect all tests to PASS.

### Task 4: LRU snapshots and the classifier training set
**Files:** Create `src/pcache/prefetch_model.py`. Tests go in `tests/test_prefetch_model.py`.

**Interfaces (produces):**
- `lru_snapshots(df, lru_capacity: int, hours: Iterable[int], seed: int = 0) -> dict[int, frozenset[int]]`.
  It replays plain LRU through `hour_requests` and returns, for each hour, the keys held at the
  start of that hour. Comment it `# shortcut: Hybrid's real LRU part also skips keys served from
  the reserved share; switch to replaying HybridCache if labels look off`.
- `training_set(counts, hours, snapshots, **feature_kwargs) -> tuple[pd.DataFrame, pd.Series]`.
  It keeps only candidates not in `snapshots[h]`, with `y = counts.loc[h] > 0` (bool).

- [ ] **Step 1: Write the failing tests:**
  - `test_snapshot_is_start_of_hour`: hour 0 requests 1, hour 1 requests 2, capacity 1. Assert
    `snapshots[1] == {1}`, and that `snapshots[0]` is empty.
  - `test_training_set_excludes_cached_and_labels`: an object in the snapshot is absent from X,
    and an object requested at h has y True.
  - `test_training_set_empty_hour`: when every candidate is cached, the function returns empty
    X and y without raising.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_prefetch_model.py -v`. Expect it to
  FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun the command. Expect all tests to PASS.

### Task 5: PrefetchModel, Hybrid wiring and versioned save/load
**Files:** Modify `src/pcache/prefetch_model.py` and `src/pcache/simulator.py`. Modify
`.gitignore` (add `models/`). Tests go in `tests/test_prefetch_model.py`.

**Interfaces (produces):**
- `PrefetchModel(capacity: int, prefetch_fraction: float = 0.10, estimator: str = "hgb", max_object_bytes: int | None = None, **params)`
- `.fit(df, train_hours) -> self` computes the snapshots at LRU size
  `capacity - max(1, int(capacity * prefetch_fraction))`, then fits the estimator on
  `training_set`.
- `.rank(counts, hour, exclude: set[int], static=None, other=None) -> list[int]` returns keys
  sorted by probability, best first. It drops excluded keys and objects larger than
  `max_object_bytes`.
- `.save(root: Path, region: str, meta: dict) -> Path` writes
  `root/<region>/v<N>/model.joblib` and `meta.json`, with N = 1 + the highest existing N.
  `meta.json` includes `capacity`, `features`, `estimator`, `train_hours` and the `meta`
  argument.
- `PrefetchModel.load(root, region, capacity, version: int | None = None) -> PrefetchModel`
  picks the highest N whose meta capacity matches. It raises `FileNotFoundError` if none
  matches.
- `iter_region(..., prefetch_model: PrefetchModel | None = None)`: when given, Hybrid's
  `prefetch` gets `prefetch_model.rank(counts, h, exclude=set(hybrid._lru._store))`, and the
  other policies keep using the count model. Training stays on hours < split. Each test hour,
  `HourResult` gets `hit_precision: float | None`, the share of the top-10 ranked keys requested
  that hour.

- [ ] **Step 1: Write the failing tests:**
  - `test_save_load_versions`: two saves give v1 and v2. `load` returns v2, and `version=1`
    returns v1.
  - `test_load_wrong_capacity_raises`: save at capacity 200, load at 50, expect
    `FileNotFoundError`.
  - `test_model_never_sees_test_hours`: fit through `iter_region` with a spy estimator. The max
    training hour is < split. This is the leakage test for training.
  - `test_iter_region_with_prefetch_model_runs`: a small synthetic frame runs with
    `prefetch_model` set. It gives finite hit rates and `hit_precision` in [0, 1].
  - `test_rank_skips_large_objects`: with `max_object_bytes=10`, an object of size 11 is not
    ranked.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_prefetch_model.py -v`. Expect it to
  FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite with `.venv/bin/python -m pytest -q`. Expect all tests to
  pass.

### Task 6: Experiments on the sample (decisions only)
**Files:** Create `scripts/experiment.py`. It is a script, not product code; it reuses the
package.

- [ ] **Step 1:** In `sample` mode, load `CDN-edge-eag` hours 0–71 through `load_source("meta", ...)`.
  Use time-ordered CV (`TimeSeriesSplit(n_splits=4)` over training hours 0–35, scored by
  average precision) to pick the estimator parameters (max_iter ∈ {100, 300},
  learning_rate ∈ {0.05, 0.1}, max_leaf_nodes ∈ {15, 31}).
- [ ] **Step 2:** On sample hours 36–71, at capacity 200, compare Hybrid against LRU for
  prefetch_fraction ∈ {0.05, 0.10, 0.20}, label "≥1 request" against "weighted by requests", and
  max_object_bytes ∈ {None, p90, p99 of sizes}. Write `reports/sample_experiments.csv`.
- [ ] **Step 3:** Install LightGBM into a scratch venv (never into `pyproject.toml`) and repeat
  Step 1 with `estimator="lgbm"`. Add `lightgbm` to `pyproject.toml` only if it beats HGB on
  sample Hybrid hit rate by more than the noise threshold.
- [ ] **Step 4:** Pick the configuration. If no configuration beats LRU on the sample, stop and
  report that plainly; leave the default unchanged.

### Task 7: Final confirmation, saved models, before/after table
- [ ] **Step 1:** In `full` mode, for every region at capacities 50, 200 and 1000, fit the
  chosen configuration on hours < 96. Replay with `prefetch_model`. Save the model through
  `.save(Path("models"), region, meta)`, with the metrics in meta.
- [ ] **Step 2:** Write `reports/before_after.csv` and print the table. Per region and capacity
  it shows LRU, LFU, old Hybrid (from `reports/baseline.csv`) and new Hybrid. Each policy gets
  hit rate % and byte hit rate %. The baseline has no byte hit rate, so each region and capacity
  also gets one replay without `prefetch_model`, which supplies the old Hybrid's bytes. It also shows the old model's precision@10 and the new model's hit precision@10.
- [ ] **Step 3:** Apply the keep rule (capacity 200, every region, > threshold). Report the
  result in plain words.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q`. Expect all tests to pass.

### Task 8: Review
- [ ] Run the ecc code review (`ecc:code-review`) on the working tree. Fix confirmed issues and
  rerun the tests.
