"""Download Wikipedia hourly pageview dumps and convert them to pcache format.

Wikipedia language editions stand in for regions:
  de -> Frankfurt, hi -> Mumbai, en -> Virginia
Each Wikipedia article stands in for a video. Output columns: region,hour,video_id
Article titles are written alongside: region,video_id,title
"""
from __future__ import annotations
import argparse, gzip, logging, urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
URL = "https://dumps.wikimedia.org/other/pageviews/{y}/{y}-{m:02d}/pageviews-{y}{m:02d}{d:02d}-{H:02d}0000.gz"
REGIONS = {"de": "Frankfurt", "hi": "Mumbai", "en": "Virginia"}
SKIP_PREFIXES = ("Special:", "File:", "Wikipedia:", "Talk:", "User:", "Category:", "Portal:", "Help:", "Template:")
# Wikimedia rejects (403) the default Python-urllib User-Agent; its policy asks for a descriptive one.
USER_AGENT = "predictive-cdn-cache/0.1 (research simulation; python-urllib)"


def download_hour(ts: datetime, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{ts:%Y%m%d-%H}.gz"
    if not path.exists():
        url = URL.format(y=ts.year, m=ts.month, d=ts.day, H=ts.hour)
        log.info("downloading %s", url)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
        tmp.rename(path)  # only cache complete downloads
    return path


def parse_hour(raw, hour: int) -> pd.DataFrame:
    """Parse one hourly dump -> rows (region, hour, page, views), cleaned."""
    if isinstance(raw, Path):
        raw = raw.read_bytes()
    text = gzip.decompress(raw).decode("utf-8", errors="replace")
    rows = []
    for line in text.splitlines():
        parts = line.split(" ")
        if len(parts) < 3:
            continue                      # malformed line
        project, page, views = parts[0], parts[1], parts[2]
        if project not in REGIONS:
            continue
        if page in ("-", "Main_Page") or page.startswith(SKIP_PREFIXES):
            continue                      # non-content / meta pages
        try:
            v = int(views)
        except ValueError:
            continue
        if v > 0:
            rows.append((REGIONS[project], hour, page, v))
    df = pd.DataFrame(rows, columns=["region", "hour", "page", "views"])
    return df.groupby(["region", "hour", "page"], as_index=False)["views"].sum()


def page_ids(g: pd.DataFrame, top_pages: int) -> dict[str, int]:
    """One region's most-viewed pages -> video ids (alphabetical, so ids are stable)."""
    keep = g.groupby("page")["views"].sum().nlargest(top_pages).index
    return {p: i for i, p in enumerate(sorted(keep))}


def to_requests(agg: pd.DataFrame, top_pages: int, requests_per_hour: int, seed: int) -> pd.DataFrame:
    """Keep each region's most-viewed pages, map them to ids, sample individual requests."""
    rng = np.random.default_rng(seed)
    out = []
    for region, g in agg.groupby("region"):
        ids = page_ids(g, top_pages)
        g = g[g["page"].isin(ids)]
        for hour, gh in g.groupby("hour"):
            p = gh["views"].to_numpy(float); p /= p.sum()
            vids = rng.choice(gh["page"].map(ids).to_numpy(), requests_per_hour, p=p)
            out.append(pd.DataFrame({"region": region, "hour": hour, "video_id": vids}))
    return pd.concat(out, ignore_index=True).sort_values(["region", "hour"], kind="stable")


def to_titles(agg: pd.DataFrame, top_pages: int) -> pd.DataFrame:
    """Readable title for every video id that to_requests produces."""
    out = []
    for region, g in agg.groupby("region"):
        ids = page_ids(g, top_pages)
        out.append(pd.DataFrame({"region": region, "video_id": list(ids.values()),
                                 "title": [p.replace("_", " ") for p in ids]}))
    return pd.concat(out, ignore_index=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2026-11-01T00", help="first hour, e.g. 2026-11-01T00")
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--top-pages", type=int, default=20000)
    ap.add_argument("--requests-per-hour", type=int, default=2000)
    ap.add_argument("--cache-dir", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/wiki_requests.csv"))
    ap.add_argument("--titles-out", type=Path, default=Path("data/wiki_titles.csv"))
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    start = datetime.strptime(a.start, "%Y-%m-%dT%H")
    frames = [parse_hour(download_hour(start + timedelta(hours=h), a.cache_dir), h) for h in range(a.hours)]
    agg = pd.concat(frames)
    req = to_requests(agg, a.top_pages, a.requests_per_hour, a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    req.to_csv(a.out, index=False)
    a.titles_out.parent.mkdir(parents=True, exist_ok=True)
    to_titles(agg, a.top_pages).to_csv(a.titles_out, index=False)
    print(f"wrote {len(req):,} requests to {a.out} and titles to {a.titles_out}")


if __name__ == "__main__":
    main()
