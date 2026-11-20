# Predictive CDN Cache

Simulates regional CDN edge caches (Frankfurt, Mumbai, Virginia) and compares classic
policies (LRU, LFU) with ML-driven predictive pre-caching (Predictive, Hybrid).

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

# Live dashboard (two pages: "app" = classic view, "live view" = redesigned view)
streamlit run dashboard/app.py
```

The **live view** page (`dashboard/pages/live_view.py`) shows trending videos as interactive
bubbles, real Wikipedia article titles (from `data/wiki_titles.csv`, written by
`prepare_wikipedia.py`) and per-policy hit rates. Its whole look (colours, fonts, CSS,
components) lives in `dashboard/ui/`: `theme.py` (design tokens + CSS), `layout.py` (one
function per section), `content.py` (data shaping) and `bubbles.html` (D3 physics component).

The first half of the hours trains the popularity model (warm-up); all hit rates and
prediction metrics are measured on the second, held-out half.

## Datasets

| Dataset | Regions | Hours | Script | Output |
|---|---|---|---|---|
| Synthetic (Zipf + viral spikes) | Frankfurt, Mumbai, Virginia | 72 | built in (`--generate`) | – |
| Wikipedia hourly pageviews | de→Frankfurt, hi→Mumbai, en→Virginia | 48 | `scripts/prepare_wikipedia.py` | `data/wiki_requests.csv` |
| Meta CDN traces (cacheMon) | one per edge cluster: eag, nha, prn | 168 | `scripts/prepare_cachemon.py` | `data/cachemon_requests.csv` |

### Meta CDN request traces (cacheMon)

Real request logs from three Meta CDN edge clusters (eag, nha, prn), 7 consecutive days,
15–22 March 2023. Columns used: `timestamp` (ms, bucketed to hours from the trace start)
and `cacheKey` (anonymised object id, mapped to an integer `video_id`). The most-requested
objects per cluster are kept (`--top-objects`, default 20000) with **every** request to them.
`data/cachemon_titles.csv` keeps each object's readable id (`cacheKey` without its zero
padding), `cdn_content_type_id` and size (`objectSize`, else `responseSize`); the live view
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

Results (hit rate %, capacity 200, held-out hours):

| Cluster | LRU | LFU | Predictive | Hybrid | precision@10 |
|---|---|---|---|---|---|
| eag | 89.22 | 69.13 | 89.23 | 70.17 | 0.46 |
| nha | 77.62 | 21.42 | 77.62 | 28.17 | 0.33 |
| prn | 80.13 | 56.54 | 80.13 | 58.86 | 0.43 |

On real CDN traffic recency wins: LFU fills up with objects that were popular days ago,
and the model's picks are almost always already in the LRU cache.

**Source and credit:** [cacheMon/cache_dataset](https://github.com/cacheMon/cache_dataset),
Meta CDN traces originally released via [CacheLib](https://cachelib.org/docs/Cache_Library_User_Guides/Cachebench_FB_HW_eval/),
licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changes made: only
`timestamp`, `cacheKey`, `objectSize`, `responseSize` and `cdn_content_type_id` are used,
keys are hashed and re-numbered, and requests are filtered to each cluster's
most-requested objects. Wikipedia pageviews:
[Wikimedia dumps](https://dumps.wikimedia.org/other/pageviews/) (CC0).
