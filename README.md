# Predictive CDN Cache

Simulates regional CDN edge caches (Frankfurt, Mumbai, Virginia) and compares classic
policies (LRU, LFU) with ML-driven predictive pre-caching (Predictive, Hybrid).

New here? Read [How it works](docs/HOW_IT_WORKS.md).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q

# Compare policies on synthetic traffic
pcache simulate --generate --capacity 200

# Real traffic: Wikipedia hourly pageviews (de -> Frankfurt, hi -> Mumbai, en -> Virginia)
python scripts/prepare_wikipedia.py --hours 48          # ~40 MB per hour downloaded
pcache simulate --data data/wiki_requests.csv --capacity 200

# Charts (PNG) + metrics.csv
pcache report --generate --capacity 200 --out reports/synthetic
pcache report --data data/wiki_requests.csv --capacity 200 --out reports/wikipedia

# Live dashboard: FastAPI + web page at http://localhost:8000
uvicorn api.main:app --port 8000
```

The dashboard reads PostgreSQL (table `requests_hourly`) when `PGHOST` is set, using `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD` and `PGSSLMODE` (see `.env.example`; load them with
`set -a; source .env; set +a`). Otherwise it reads the CSV in `PCACHE_CSV`
(default `data/requests_hourly.csv`; one row per request, or hourly counts with a `requests` column).
Only the selected region is loaded. Titles come from `PCACHE_TITLES` or the matching `*_titles.csv`.

API: `GET /api/health`, `GET /api/regions`, `POST /api/simulate/start` (`{"region", "capacity", "speed"}`),
`POST /api/simulate/pause`, `POST /api/simulate/reset`, and the WebSocket `/ws/live`, which sends the full
state on connect and on every start/pause/reset, then one message per simulated hour. There is one shared
simulation, so every open page shows the same run.

Docker (credentials are passed at run time, never built in):

```bash
docker build -t pcache .
docker run --env-file .env -p 8000:8000 pcache                  # PostgreSQL
docker run -v "$PWD/data:/app/data:ro" -p 8000:8000 pcache      # local CSV
```

**Policies.** LRU and LFU are the classic baselines. *Predictive* is an LRU cache that each
hour also loads the model's top predicted items, skipping those it already holds. *Hybrid*
is an LRU cache plus a reserved share (default 10% of capacity) for the model's top predicted
items that the LRU part does not hold. The model (gradient boosting) uses each item's requests
1, 2, 3, 6 and 24 hours ago, its growth, its 6-hour mean and the hour of day.

The page (`web/`: `index.html`, `style.css`, `app.js`, `bubbles.js`, plain JavaScript + D3) shows four
metric cards, the live hit-rate chart, trending videos as draggable Liquid Glass bubbles and the
predicted-vs-actual top 10 with trend tags. `api/content.py` shapes the data it shows.

The first half of the hours trains the popularity model (warm-up); all hit rates and
prediction metrics are measured on the second, held-out half.

## Datasets

To plug in a new source, see [docs/data-sources.md](docs/data-sources.md).

| Dataset | Regions | Hours | Script | Output |
|---|---|---|---|---|
| Synthetic (Zipf + viral spikes) | Frankfurt, Mumbai, Virginia | 72 | built in (`--generate`) | – |
| Wikipedia hourly pageviews | de→Frankfurt, hi→Mumbai, en→Virginia | 48 | `scripts/prepare_wikipedia.py` | `data/wiki_requests.csv` |
| Meta CDN traces (cacheMon) | one per edge cluster: eag, nha, prn | 193 | `scripts/prepare_cachemon.py` | `data/cachemon_requests.csv` |

### Meta CDN request traces (cacheMon)

Real request logs from three Meta CDN edge clusters (eag, nha, prn), 193 hourly buckets
(about 8 days), 15–22 March 2023. Columns used: `timestamp` (ms, bucketed to hours from the trace start)
and `cacheKey` (anonymised object id, mapped to an integer `video_id`). The most-requested
objects per cluster are kept (`--top-objects`, default 20000) with **every** request to them.
`data/cachemon_titles.csv` keeps each object's readable id (`cacheKey` without its zero
padding), `cdn_content_type_id` and size (`objectSize`, else `responseSize`); the live dashboard
shows them as bubble labels and type/size tags.

```bash
mkdir -p data/raw/cachemon && cd data/raw/cachemon
B=https://cache-datasets.s3.amazonaws.com/cache_dataset_txt/2023_metaCDN
curl -O $B/reag0c01_20230315_20230322_0.2000.csv.zst   # 0.63 GB
curl -O $B/rnha0c01_20230315_20230322_0.8000.csv.zst   # 1.66 GB
curl -O $B/rprn0c01_20230315_20230322_0.2000.csv.zst   # 1.44 GB
cd ../../..
python scripts/prepare_cachemon.py                      # all files -> CDN-edge-eag/nha/prn
python scripts/prepare_cachemon.py data/raw/cachemon/reag0c01_*.zst --max-rows 4000000 \
    --out data/cachemon_sample_requests.csv             # quick sample, region "CDN-edge"
pcache simulate --data data/cachemon_requests.csv --capacity 200
pcache report --data data/cachemon_requests.csv --capacity 200 --out reports/cachemon
```

Files are streamed (never fully decompressed, ~46 GB uncompressed). On an 8 GB Mac:
preparing takes ~15 min (~3.8 GB peak), giving 57M requests (1.2 GB CSV); `simulate` takes
~9 min and `report` ~6 min (~3 GB peak each).

Results (hit rate %, capacity 200, held-out hours 96-192; from `reports/baseline.csv`):

| Cluster | LRU | LFU | Predictive | Hybrid | precision@10 |
|---|---|---|---|---|---|
| eag | 80.97 | 69.13 | 80.98 | 81.18 | 0.39 |
| nha | 50.53 | 21.42 | 50.55 | 50.93 | 0.32 |
| prn | 67.42 | 56.54 | 67.43 | 67.80 | 0.41 |

**Finding: on real CDN traffic, recency wins and prediction adds little.** What gets
requested next is mostly what was requested a moment ago, so plain LRU is hard to beat. LFU
loses badly because it hoards objects that were popular days ago. Predictive stays within
0.02 points of LRU: the items the model can see coming are already in the LRU cache. Hybrid
(10% of the slots reserved for model picks) is ahead of LRU by 0.2-0.4 points in every
cluster at cache size 200 (0.20-0.47 across three seeds). The model gets about 3 to 4 of its
top 10 right (precision@10 0.32-0.41). Other cache sizes, the seed runs and a newer
classifier that was not adopted are in
[How it works](docs/HOW_IT_WORKS.md#7-results-and-the-honest-finding).

**Source and credit:** [cacheMon/cache_dataset](https://github.com/cacheMon/cache_dataset),
Meta CDN traces originally released via [CacheLib](https://cachelib.org/docs/Cache_Library_User_Guides/Cachebench_FB_HW_eval/),
licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changes made: only
`timestamp`, `cacheKey`, `objectSize`, `responseSize` and `cdn_content_type_id` are used,
keys are hashed and re-numbered, and requests are filtered to each cluster's
most-requested objects. Wikipedia pageviews:
[Wikimedia dumps](https://dumps.wikimedia.org/other/pageviews/) (CC0).
