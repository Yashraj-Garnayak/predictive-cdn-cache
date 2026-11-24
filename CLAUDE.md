# Project memory: Predictive CDN Cache

Read this file first, every session. Keep it up to date: at the end of every task, update "Current status" and "Decisions" (short, no long logs).

## About the user
- Yashraj, M.Sc. High Integrity Systems, Frankfurt UAS. Aiming for DevOps / cloud roles.
- Knows Docker basics and AWS; new to ML, Azure and Terraform.
- Explain in plain words first, then the technical terms. One step at a time.
- Version 2 (cloud) is a learning phase: he writes Docker Compose, Azure and Terraform himself. Guide, explain and review; don't write those parts unless he asks.

## Skills to use
- superpowers: plan before big changes, test-first, systematic debugging.
- karpathy skills: simple, small, surgical, goal-driven changes.
- ecc: workflow and code review at the end of a task.
- ponytail: installed, use where it fits.
- UI UX Pro Max: all dashboard / UI design.
- MotionSites Web Builder: animated web pages (e.g. a landing page).
- graphify: use the code graph (graphify-out/, git-ignored) to find things instead of reading whole files; rebuild it after big changes (code only: src, api, web, tests, scripts).

## What the project is
Simulates CDN edge caches and compares four policies:
- LRU (Least Recently Used), LFU (Least Frequently Used),
- Predictive (LRU + ML model pre-loading expected items),
- Hybrid (LRU + a reserved share, default 10%, for model picks LRU doesn't hold).
Models:
- Count model (default, feeds Predictive, Hybrid, API and dashboard): gradient boosting regression on lags 1, 2, 3, 6, 24 h, growth, 6 h average, hour of day.
- Prefetch classifier (src/pcache/prefetch_model.py, opt-in via `iter_region(prefetch_model=...)`): predicts "requested this hour and NOT in LRU", weighted by request count; extra features EWM, hours since first seen, size, content type; weekly (lag 168, day of week) and cross-region features switch on automatically when the data supports them.

## Data
- Meta CDN traces, 15–22 March 2023, github.com/cacheMon/cache_dataset (CC BY 4.0). Clusters eag, nha, prn; 193 hours (about 8 days); the 20,000 most-requested objects per cluster with every request to them.
- data/cachemon_requests.csv (one row per request, about 57M rows); data/cachemon_titles.csv (object type and size); data/requests_hourly.csv (region, hour, video_id, requests; 2.9M rows — the main input).
- PostgreSQL has two tables: requests_hourly and titles (region, video_id, title, content_type, size_bytes). In database mode the dashboard needs no local data files (titles, types and sizes come from the titles table; if it is missing the bubbles show "Video <id>" and the server logs a warning).
- New sources go through src/pcache/sources.py (standard format region, hour, object_id, requests, optional size_bytes/content_type, with validation); how-to in docs/data-sources.md.
- The clusters share zero objects, so cross-region features don't help here.
- Wikipedia data (48 h, no sizes) is still in data/ and has an adapter, but is not used for results; synthetic data for quick demos.
- Experiment on a sample (first 3 days of CDN-edge-eag); confirm only the winner on full data (one full replay takes 1–5 minutes per region and cache size).

## Key results (cache 200, real Meta data, held-out hours)
- LRU 51–81% hit rate (eag 81.0, nha 50.5, prn 67.4); LFU 21–69% (keeps items popular days ago).
- Predictive ties LRU (+0.01–0.02 points): its picks are mostly already in LRU.
- Old Hybrid (count model, 10% share) beats LRU by +0.2–0.4 points in every region (replay noise ≤ 0.07).
- New Hybrid (prefetch classifier, 20% share): eag +0.64, prn +0.63, nha −0.17 → fails the every-region rule, so it is NOT the default. It also loses 1–3 points of byte hit rate. Table: reports/before_after.csv.
- Honest finding: on real CDN traffic, recency wins. An improvement only counts if it beats LRU's hit rate on held-out hours.

## Architecture
- src/pcache/: policies, features, model (count model), prefetch_model (classifier + versioned save/load), simulator, sources (adapters), data (CSV loaders), db (PostgreSQL), report, CLI (pcache).
- scripts/: prepare_cachemon.py, prepare_wikipedia.py, experiment.py (sample tuning and full confirmation).
- api/: FastAPI (/api/health, /api/regions, /api/simulate/start|pause|reset, WebSocket /ws/live).
- web/: custom dashboard (index.html, app.js, bubbles.js with D3, style.css: dark glass, live chart, bubbles, predicted vs actual). Streamlit removed.
- Data source: PostgreSQL via env vars (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE=require); otherwise CSV from PCACHE_CSV (default data/requests_hourly.csv); titles: PCACHE_TITLES > database titles table > matching *_titles.csv > cachemon_titles.csv beside the CSV.
- Saved models: models/<region>/v<N>/model.joblib + meta.json (capacity inside meta.json; git-ignored).

## Infrastructure
- Docker: multi-stage, non-root user "app", uvicorn on port 8000, image about 761 MB; data mounted from outside (stateless). Models are not mounted yet.
- docker-compose.yml: app service, env_file .env, port 8000, ./data mounted read-only.
- Azure for Students: PostgreSQL flexible server, Burstable B1ms, 32 GB, public access limited to his IP; table requests_hourly in database "postgres", indexed on (region, hour).
- Student policy allows only norwayeast, polandcentral, switzerlandnorth, germanywestcentral, swedencentral (Germany West Central refused PostgreSQL in practice).
- Budget alert 10 EUR; stop the database when not in use.

## Rules
- Never put secrets in code, the image, git or this file; secrets live only in .env (git- and docker-ignored).
- Don't commit or push unless he explicitly says so.
- Run all tests after every change (`.venv/bin/python -m pytest -q`); report results honestly.
- Don't touch data files unless asked.
- Explain each change in plain words at the end.
- Save tokens: read this file, use graphify, use samples for experiments.

## Roadmap
1. Done: simulator, ML model, real Meta data, custom dashboard, Docker image, Azure PostgreSQL with data.
2. Done (result: not adopted): stronger prediction (target "requested but not in LRU", better features, HistGradientBoosting vs LightGBM — LightGBM did not win, not added — cache 200 main + 50 and 1000), data-source adapters, byte hit rate, versioned model saving.
3. Next: everything local with Docker Compose, then push the image to Docker Hub.
4. Then: Azure by hand (VM + Docker), then Terraform (make up / make down), then CI/CD with GitHub Actions (tests and plan on push, manual apply button).
5. Later: EDA notebook and filter script; GitHub README and CV line.

## Current status
- 89 tests passing. Bubbles are labelled "Video <id>" with a "Type N" chip (hidden on small bubbles); the hover tooltip shows type, size, requests, predicted/missed, trend and region (data fields label/type/size/region from api/content.py bubble_data). Dashboard and API run in Docker on port 8000.
- web/how-it-works.html: 10-step animated explainer (no libraries). Opens inside the dashboard as a full-screen overlay (`<dialog>` + iframe with `?embed`, loaded on first open) from the header button, a "?" on each section (jumps to the matching step), or a one-time first-visit hint (localStorage key `pcache.hiw-hint-seen`). Still works as a standalone page. Docs: docs/DASHBOARD_GUIDE.md.
- Prediction work finished (see Key results). Design and plan: docs/superpowers/specs/ and docs/superpowers/plans/ (2026-11-22).
- Open review items: API headline `hybrid_lead` still compares Hybrid with LFU (api/main.py:118); custom `policies` list in iter_region is fragile; progress bar assumes a 50/50 split; replay of big regions is slow.

## Decisions
- Hybrid is built on LRU; its headline lead should be measured against LRU (not yet changed in api/main.py).
- A change is kept only if Hybrid beats LRU at cache 200 in every region by more than 0.2 points.
- Models are trained once, saved and loaded; a retrained version should replace the old one only if it scores at least as well (not enforced yet: save always adds v<N+1>, load picks the newest for that capacity).
- LightGBM not added (no gain over HistGradientBoosting); prefetch size limit not used (did not improve byte hit rate).
