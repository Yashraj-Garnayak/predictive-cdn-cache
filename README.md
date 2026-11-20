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

# Live dashboard
streamlit run dashboard/app.py
```

The first half of the hours trains the popularity model (warm-up); all hit rates and
prediction metrics are measured on the second, held-out half.
