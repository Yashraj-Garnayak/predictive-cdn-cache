# Design: make prediction beat LRU, and make new data sources easy

Date: 2026-11-22. Status: approved by owner. Not committed (owner's instruction).

## Intent
Today the prediction-based Hybrid cache does not clearly beat plain LRU. The goal is a Hybrid that
beats LRU on held-out hours, proven against a recorded baseline. It should also be easy to feed the
simulator from more data sources than the two prepared CSVs.

## Goals
1. **Baseline first.** Record the current LRU, LFU, Predictive and Hybrid hit rates (and precision@10)
   per region, at cache sizes 50, 200 and 1000, on the full Meta data (`data/requests_hourly.csv`).
   Save it to `reports/baseline.csv`. Every later change is compared against it.
2. **Keep rule.** A change is kept only if Hybrid's hit rate beats LRU on held-out hours at
   **capacity 200** (the main test), in **every one of the 3 regions**, by more than replay noise
   (measured by rerunning with several shuffle seeds; at least 0.2 points). Report 50 and 1000 too. If nothing beats LRU, say so plainly
   and leave the old model in place.
3. **One standard input format** for every source: `region, hour, object_id, requests`, with
   optional `size_bytes` and `content_type`. Each source gets a small adapter function. There is
   one shared `validate()`, which rejects missing columns, duplicate (region, hour, object_id)
   rows, bad hours (negative, non-integer or missing) and non-positive requests. Document how to
   add a source.
4. **New target.** Predict, per hour, which objects are requested this hour AND are not in the
   LRU part of Hybrid at the start of the hour. This is a classifier. Hybrid's reserved slots go
   to the highest probabilities.
5. **Features:** lags 1, 2, 3, 6 and 24; growth rate; exponentially weighted average; hours since
   first seen; hour of day; size and content type when present.
   **Optional features that switch on automatically:** lag 168 and day of week, when the training
   hours include at least 168 hours of history; cross-region recent requests, when an object id
   appears in more than one region. On the Meta data neither applies (8 days; no objects shared
   across regions), so they stay off there.
6. **Model:** HistGradientBoosting (current) versus LightGBM, tuned with time-based cross-validation
   only (folds ordered by hour, always train on earlier hours and validate on later ones). Keep the
   simplest model that wins. LightGBM is added as a dependency **only if it wins**.
7. **Size-aware:** report byte hit rate next to hit rate. Let Hybrid skip prefetch candidates above
   a size limit, and keep the limit only if it improves byte hit rate without losing the
   hit-rate win.
8. **Leakage:** an explicit test that features and labels for hour h do not change when hours ≥ h
   are altered, and that the model never trains on held-out hours.
9. **Saved models:** `models/<region>/v<N>/` holding `model.joblib` plus `meta.json` (features,
   model type, training hours, data source, metrics). Each save picks the next N; load reads the
   highest N unless one is given. Uses joblib, which is already installed.

## Non-goals
- Dashboard or web changes beyond what keeps them working. The API keeps using `iter_region` and
  `POLICY_NAMES`.
- Size-based cache capacity. Capacity stays an object count; bytes are reported, not budgeted.
- Model-chosen eviction (too slow: one model call per request across 57M requests).
- Fixing review findings #7 to #10.

## Anti-goals (a failure even if it "works")
- A win that comes from leakage: training on test hours, or features built from the current or
  later hours.
- A win reported on the sample only. The final claim is on the full data.
- Adding LightGBM, or features, that do not improve the result.

## Constraints
- **Experiments are slow:** one full Meta replay takes about 9 minutes. Iterate on a sample (the
  first 72 hours of `CDN-edge-eag`). Confirm only the final candidate on all three regions at
  sizes 50, 200 and 1000.
- Train only on the first half of each region's hours. Tune within those hours with time-ordered
  cross-validation. The second half is held out and touched only for the final report.
- Meta data: 3 regions, 193 hours, 20k objects each, about 57M requests. Sizes and content types
  come from `data/cachemon_titles.csv`. The Wikipedia data: 3 regions, 48 hours, no sizes.
- Test-first: each behaviour gets a failing test before the code.
- No commits.

## Approaches considered (owner handed over the how; builder's pick is A)
- **A. Reserved-share Hybrid with a new ranking (picked).** Keep Hybrid as it is (an LRU plus a
  reserved share for predicted items the LRU part does not hold). Change only what ranks the
  candidates: the "requested and not in LRU" probability. This is the smallest change, and it
  aims straight at the gap LRU leaves.
- **B. Prefetch into the LRU itself** (the existing `Predictive` policy). Prefetched items compete
  with LRU's own items. It tied LRU in earlier runs. It stays in the report as a comparison.
- **C. Model-driven eviction.** Rejected as too slow.

## How the parts fit
- `src/pcache/sources.py`: `validate(df)` plus `ADAPTERS = {"meta": ..., "wikipedia": ...,
  "hourly_csv": ...}`. Each adapter takes paths and returns a validated standard frame. The column
  is renamed `object_id` → `video_id` at this one boundary, so the rest of the code is untouched
  (builder's call, marked with a `shortcut:` comment).
- `features.py`: the feature set above, with optional features gated on what the data has.
- `model.py`: `PopularityModel` keeps `fit` and `predict`, with a classifier target and a
  pluggable estimator. `save` and `load` use the versioned layout.
- `simulator.py`: during the training hours, replay LRU (at Hybrid's LRU size) to record which
  objects it held at the start of each hour. These snapshots build the labels and the
  "not in LRU" candidate filter. Policies also count bytes.
- `report.py` and the CLI: add a byte hit rate column, and a before/after table per region and
  size (LRU, LFU, old Hybrid, new Hybrid: hit rate, byte hit rate, precision@10).
- `docs/data-sources.md`: how to add a source.

## Settled after the builder check
- **Which numbers decide in-between choices (answered).** Every tuning decision is made on the
  sample: hours 0–71 of `CDN-edge-eag`, trained on hours 0–35 with time-ordered CV and scored on
  hours 36–71. All of those hours fall inside the full data's training half (the split is at
  hour 96), so the full held-out hours (96–192) are used once, for the final report.
- **Baseline file (answered).** `data/requests_hourly.csv` (hourly counts, replayed in a seeded
  shuffled order within each hour). It is the API's default source and in the standard format.
  `cachemon_requests.csv` is not used.
- **One model per capacity (my call).** Labels depend on the LRU part's size, so each capacity
  gets its own model. The reserved share is tuned once on the sample, then fixed, which gives 3
  models per region. The path stays `models/<region>/v<N>/`, with `capacity` in `meta.json`.
  `load(region, capacity)` returns the highest N trained for that capacity.
- **Old and new models side by side (my call).** The count model stays as it is and keeps
  feeding Predictive, the API, the dashboard and "old Hybrid". The new classifier feeds only the
  new Hybrid. precision@10 for the old model keeps its meaning (predicted top 10 vs actual
  top 10). For the new model it means "share of its top-10 picks that were actually requested
  that hour". It is labelled differently in the table so the two are not confused.
- **Object identity across regions (my call).** The standard `object_id` must mean the same object
  in every region. The prepared CSVs number objects per region from 0, so the Meta and Wikipedia
  adapters map each object's title (cacheKey or article) to one id shared across regions. The
  cross-region feature switches on only when some object id appears in two or more regions.
  Meta: 0 shared. Wikipedia: 24 of 20,000 shared, so on but nearly empty.

## Left to the builder
- Hyperparameter grid, the EWMA span, the reserved share (tune among 5%, 10% and 20% on the
  sample) and the size-limit candidates.
- Whether labels are "requested ≥ 1" (the owner's spec, tried first), or weighted by request count
  if the plain version loses.
- File names inside `reports/`. Whether `models/` is gitignored (proposed: yes).
