"""FastAPI backend: runs the cache simulation and streams one message per simulated hour.

Run from the project root:  uvicorn api.main:app --port 8000

Data source: PostgreSQL when PGHOST is set (PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE are read
by libpq), otherwise the local CSV in PCACHE_CSV (default data/requests_hourly.csv). Only the selected
region is loaded. Titles: PCACHE_TITLES, else the database titles table, else the matching *_titles.csv
or cachemon_titles.csv beside the CSV.
"""
from __future__ import annotations
import asyncio
import logging
import os
from functools import lru_cache
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pcache import db
from pcache.data import csv_regions, load_csv_region
from pcache.report import mean_abs_error, precision_at_k
from pcache.simulator import POLICY_NAMES, iter_region
from . import content

log = logging.getLogger(__name__)
WEB = Path(__file__).parents[1] / "web"


# ---------- data source ----------
def source() -> str:
    return "database" if os.environ.get("PGHOST") else "csv"


def csv_path() -> Path:
    return Path(os.environ.get("PCACHE_CSV", "data/requests_hourly.csv")).resolve()


def regions() -> list[str]:
    return db.regions() if source() == "database" else _csv_regions(csv_path())


@lru_cache(maxsize=4)
def _csv_regions(path: Path) -> list[str]:
    return csv_regions(path)


def load_region(src: str, path: Path, region: str) -> pd.DataFrame:
    return db.load_region(region) if src == "database" else _load_csv_region(path, region)  # DB: always fresh


@lru_cache(maxsize=2)  # a region is a few hundred MB at most; keep the last two
def _load_csv_region(path: Path, region: str) -> pd.DataFrame:
    return load_csv_region(path, region)


def titles_and_tags(region: str) -> tuple[dict[int, str], dict[int, list[str]]]:
    path = os.environ.get("PCACHE_TITLES")
    if not path and source() == "database":
        try:
            return content.titles_and_tags_from(db.load_titles(region))
        except ValueError as e:
            log.warning("Titles unavailable (%s); bubbles will show 'Video <id>'", e)
            return {}, {}
    if not path:
        beside = content.titles_path(csv_path())
        path = next((p for p in (beside, csv_path().parent / "cachemon_titles.csv") if p.is_file()), None)
    if not path:
        return {}, {}
    return content.read_titles(path).get(region, {}), content.read_object_info(path).get(region, {})


def warn_untitled(df: pd.DataFrame, region: str, titles: dict[int, str]) -> None:
    ids = set(df["video_id"].unique())
    if titles and (n := len(ids - {k for k, v in titles.items() if v})):
        log.warning("%d of %d videos in %s have no title; they show as 'Video <id>'", n, len(ids), region)


# ---------- the one shared simulation ----------
class Live:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.clear()

    def clear(self) -> None:
        self.config: dict | None = None
        self.gen = None
        self.status, self.message = "idle", ""
        self.history: list[dict] = []
        self.last: dict | None = None
        self.recent: list[pd.Series] = []   # last few hours of request counts, for trend tags
        self.total = 0
        self.titles, self.tags = {}, {}

    def state(self) -> dict:
        return {"type": "state", "status": self.status, "message": self.message, "config": self.config,
                "total": self.total, "history": self.history, "last": self.last}

    def remember(self, r) -> None:
        self.recent = (self.recent + [r.actual])[-(content.TREND_HOURS + 1):]

    def step(self) -> dict | None:
        """Advance one test hour (the first call also replays the warm-up hours). Runs in a thread."""
        try:
            r = next(self.gen)
            while not r.is_test:
                self.remember(r)
                r = next(self.gen)
        except StopIteration:
            return None
        self.remember(r)
        return hour_message(r, self.recent, self.titles, self.tags, len(self.history) + 1, self.total, (self.config or {}).get("region", ""))

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:  # client went away mid-send
                self.clients.discard(ws)


def hour_message(r, recent, titles, tags, index: int, total: int, region: str = "") -> dict:
    shown = set(r.actual.nlargest(content.N_BUBBLES).index) | set(r.predicted.nlargest(content.K).index) \
        | set(r.actual.nlargest(content.K).index)
    trend_of = content.trends(recent, shown)
    return {
        "type": "hour", "hour": r.hour, "index": index, "total": total,
        "hit_rate": {p: r.running_hit_rate[p] * 100 for p in POLICY_NAMES},
        "hourly_hit_rate": {p: r.hourly_hit_rate[p] * 100 for p in POLICY_NAMES},
        "precision": precision_at_k(r.predicted, r.actual, content.K),
        "mae": mean_abs_error(r.predicted, r.actual),
        "hybrid_lead": (r.running_hit_rate["Hybrid"] - r.running_hit_rate["LFU"]) * 100,
        "top10": content.table_rows(r.predicted, r.actual, titles, trend_of=trend_of, tags=tags),
        "bubbles": content.bubble_data(r.predicted, r.actual, titles, trend_of=trend_of, tags=tags, region=region),
    }


live = Live()
RUNNING = ("warming", "playing")


async def run() -> None:
    """Background loop: one hour per 1/speed seconds until paused, reset or finished."""
    try:
        while live.status in RUNNING:
            async with live.lock:
                if live.status not in RUNNING:
                    break
                msg = await asyncio.to_thread(live.step)
                if msg is None:
                    live.status = "finished"
                    await live.broadcast(live.state())
                    break
                live.history.append({"hour": msg["hour"], "hit_rate": msg["hit_rate"]})
                live.last = msg
                if live.status == "warming":
                    live.status = "playing"
                    await live.broadcast(live.state())
                else:
                    await live.broadcast(msg)
            await asyncio.sleep(1 / live.config["speed"])
    except Exception as e:  # keep the server up; show the error in the page
        log.exception("simulation failed")
        live.status, live.message = "error", str(e)
        await live.broadcast(live.state())


# ---------- HTTP + WebSocket ----------
app = FastAPI(title="Predictive CDN Cache")


class StartRequest(BaseModel):
    region: str
    capacity: int = Field(200, ge=10, le=5000)
    speed: float = Field(1.0, ge=0.25, le=5.0)   # simulated hours per second


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "source": source()}


@app.get("/api/regions")
async def get_regions() -> dict:
    try:
        return {"source": source(), "regions": await asyncio.to_thread(regions)}
    except ValueError as e:
        raise HTTPException(503, str(e)) from e


@app.post("/api/simulate/start")
async def start(req: StartRequest) -> dict:
    try:
        if req.region not in await asyncio.to_thread(regions):
            raise HTTPException(404, f"Unknown region {req.region!r}")
        async with live.lock:
            same = live.config and (live.config["region"], live.config["capacity"]) == (req.region, req.capacity)
            if not same or live.status == "error":
                df = await asyncio.to_thread(load_region, source(), csv_path(), req.region)
                live.clear()
                live.gen = iter_region(df, req.capacity)
                live.total = df["hour"].nunique() - df["hour"].nunique() // 2
                live.titles, live.tags = await asyncio.to_thread(titles_and_tags, req.region)
                warn_untitled(df, req.region, live.titles)
            live.config = req.model_dump()   # speed can change on a running simulation
            if live.status != "finished":
                live.status = "warming" if not live.history else "playing"
            await live.broadcast(live.state())
            if live.status in RUNNING and (live.task is None or live.task.done()):
                live.task = asyncio.create_task(run())
            return {"status": live.status}
    except ValueError as e:
        raise HTTPException(503, str(e)) from e


@app.post("/api/simulate/pause")
async def pause() -> dict:
    if live.status in RUNNING:
        live.status = "paused"
        await live.broadcast(live.state())
    return {"status": live.status}


@app.post("/api/simulate/reset")
async def reset() -> dict:
    async with live.lock:   # waits for an hour in progress, so no stale hour arrives after the reset
        live.clear()
        await live.broadcast(live.state())
    return {"status": live.status}


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()
    live.clients.add(ws)
    try:
        await ws.send_json(live.state())
        while True:
            await ws.receive_text()   # clients only listen; this just notices when they leave
    except WebSocketDisconnect:
        pass
    finally:
        live.clients.discard(ws)


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
