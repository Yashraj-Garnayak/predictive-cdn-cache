"""Turn simulation results into what the live page shows (titles, trend tags, bubbles, table rows)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

K = 10            # size of the predicted-vs-actual comparison
N_BUBBLES = 20    # videos shown as Trending Now bubbles
TREND_HOURS = 3   # a video's trend compares this hour with the average of the previous 3 hours
TREND_LABELS = {"rising": "rising fast", "steady": "steady", "fading": "fading"}


def titles_path(data_path: str | Path) -> Path:
    """Titles file that belongs to a request log: data/wiki_requests.csv -> data/wiki_titles.csv."""
    p = Path(data_path)
    return p.with_name(p.name.replace("requests", "titles"))


def read_titles(path: str | Path) -> dict[str, dict[int, str]]:
    """region -> {video_id: title}; empty if the file does not exist."""
    p = Path(path)
    if not p.is_file():
        return {}
    df = pd.read_csv(p, dtype={"region": str, "video_id": int, "title": str})
    return {str(r): dict(zip(g["video_id"], g["title"].fillna(""))) for r, g in df.groupby("region")}


def title_of(video_id: int, titles: dict[int, str]) -> str:
    """Readable name for a video; synthetic data has no titles, so it falls back to 'Video <id>'."""
    return titles.get(int(video_id)) or f"Video {int(video_id)}"


def _tags(df: pd.DataFrame) -> list[list[str]]:
    types = df["content_type"] if "content_type" in df else pd.Series(None, index=df.index, dtype=object)
    sizes = df["size_bytes"] if "size_bytes" in df else pd.Series(None, index=df.index, dtype=object)
    return [[t for t in (f"Type {ct}" if pd.notna(ct) and ct != "" else "", format_size(sb) if pd.notna(sb) else "") if t]
            for ct, sb in zip(types, sizes)]


def titles_and_tags_from(df: pd.DataFrame) -> tuple[dict[int, str], dict[int, list[str]]]:
    """Titles and tags for one region's rows (video_id, title, optional content_type, size_bytes)."""
    ids = df["video_id"].astype(int)
    return dict(zip(ids, df["title"].fillna(""))), dict(zip(ids, _tags(df)))


def read_object_info(path: str | Path) -> dict[str, dict[int, list[str]]]:
    """region -> {video_id: tags like ['Type 3', '21.0 KB']} from the titles file's optional
    content_type / size_bytes columns (written by prepare_cachemon.py); empty if absent."""
    p = Path(path)
    if not p.is_file():
        return {}
    df = pd.read_csv(p, dtype={"region": str, "video_id": int, "content_type": str})
    if "content_type" not in df and "size_bytes" not in df:
        return {}
    df["tags"] = _tags(df)
    return {str(r): dict(zip(g["video_id"], g["tags"])) for r, g in df.groupby("region")}


def format_size(n_bytes: float) -> str:
    """1536 -> '1.5 KB'; 0 or unknown -> ''."""
    if not n_bytes or n_bytes <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1000 or unit == "GB":
            return f"{n_bytes:.0f} {unit}" if unit == "B" or n_bytes >= 100 else f"{n_bytes:.1f} {unit}"
        n_bytes /= 1000
    return ""


def trend(now: float, before: float) -> str:
    """'rising' / 'steady' / 'fading': requests this hour vs the average of the previous hours.
    Adding 2 to both sides keeps tiny counts (1 -> 2 requests) from being called a surge."""
    ratio = (now + 2) / (before + 2)
    return "rising" if ratio >= 1.5 else "fading" if ratio <= 1 / 1.5 else "steady"


def trends(recent: list[pd.Series], ids) -> dict[int, str]:
    """Trend per video id. recent = per-hour request counts, oldest first, ending with this hour."""
    if len(recent) < 2:
        return {}
    now = recent[-1]
    before = pd.concat(recent[-1 - TREND_HOURS:-1], axis=1).fillna(0).mean(axis=1)
    return {int(v): trend(float(now.get(v, 0)), float(before.get(v, 0))) for v in ids}


def bubble_data(predicted: pd.Series, actual: pd.Series, titles: dict[int, str],
                n: int = N_BUBBLES, trend_of: dict[int, str] | None = None,
                tags: dict[int, list[str]] | None = None, region: str = "") -> list[dict]:
    """This hour's n most-requested videos; 'hit' = the model had it among its n top picks.
    'trend' is 'rising' / 'steady' / 'fading' (None before there is history). 'label' is the bubble's
    main text; 'type' / 'size' (None when the titles table has no row or no value) feed the chip and tooltip."""
    picks = set(predicted.nlargest(n).index)
    trend_of, tags = trend_of or {}, tags or {}
    out = []
    for v, c in actual.nlargest(n).items():
        if c <= 0:
            continue
        t = list(tags.get(int(v), []))
        out.append({"id": int(v), "label": f"Video {int(v)}", "title": title_of(v, titles), "actual": int(c),
                    "predicted": round(float(predicted.get(v, 0.0)), 1), "hit": v in picks,
                    "trend": trend_of.get(int(v)), "tags": t, "region": region,
                    "type": next((x for x in t if x.startswith("Type ")), None),
                    "size": next((x for x in t if not x.startswith("Type ")), None)})
    return out


def table_rows(predicted: pd.Series, actual: pd.Series, titles: dict[int, str], k: int = K,
               trend_of: dict[int, str] | None = None, tags: dict[int, list[str]] | None = None) -> list[dict]:
    """Rank-by-rank model top k vs real top k; 'match' = the video is in both lists."""
    p, a = predicted.nlargest(k), actual.nlargest(k)
    trend_of, tags = trend_of or {}, tags or {}
    rows = []
    for rank in range(k):
        pv = int(p.index[rank]) if rank < len(p) else None
        av = int(a.index[rank]) if rank < len(a) else None
        rows.append({
            "rank": rank + 1,
            "pred_title": title_of(pv, titles) if pv is not None else "",
            "pred_count": float(p.iloc[rank]) if pv is not None else None,
            "pred_match": pv in a.index,
            "pred_trend": trend_of.get(pv), "pred_tags": list(tags.get(pv, [])),
            "act_title": title_of(av, titles) if av is not None else "",
            "act_count": int(a.iloc[rank]) if av is not None else None,
            "act_match": av in p.index,
            "act_trend": trend_of.get(av), "act_tags": list(tags.get(av, [])),
        })
    return rows
