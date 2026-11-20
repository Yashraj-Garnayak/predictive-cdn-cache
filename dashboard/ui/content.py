"""Turn simulation results into what the live view shows (titles, bubbles, table rows, metrics)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

K = 10            # size of the predicted-vs-actual comparison
N_BUBBLES = 20    # videos shown as Trending Now bubbles


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


def bubble_data(predicted: pd.Series, actual: pd.Series, titles: dict[int, str],
                n: int = N_BUBBLES) -> list[dict]:
    """This hour's n most-requested videos; 'hit' = the model had it among its n top picks."""
    picks = set(predicted.nlargest(n).index)
    return [{"id": int(v), "title": title_of(v, titles), "actual": int(c),
             "predicted": round(float(predicted.get(v, 0.0)), 1), "hit": v in picks}
            for v, c in actual.nlargest(n).items() if c > 0]


def table_rows(predicted: pd.Series, actual: pd.Series, titles: dict[int, str], k: int = K) -> list[dict]:
    """Rank-by-rank model top k vs real top k; 'match' = the video is in both lists."""
    p, a = predicted.nlargest(k), actual.nlargest(k)
    rows = []
    for rank in range(k):
        pv = int(p.index[rank]) if rank < len(p) else None
        av = int(a.index[rank]) if rank < len(a) else None
        rows.append({
            "rank": rank + 1,
            "pred_title": title_of(pv, titles) if pv is not None else "",
            "pred_count": float(p.iloc[rank]) if pv is not None else None,
            "pred_match": pv in a.index,
            "act_title": title_of(av, titles) if av is not None else "",
            "act_count": int(a.iloc[rank]) if av is not None else None,
            "act_match": av in p.index,
        })
    return rows


def delta(now: float, before: float | None, fmt: str, higher_is_better: bool = True) -> tuple[str, str] | None:
    """Change since the previous hour as (text, 'good' | 'bad' | 'flat'), or None for the first hour."""
    if before is None:
        return None
    d = now - before
    text = fmt.format(d)
    if not any(c in "123456789" for c in text):   # rounds to zero, e.g. "+0.00"
        return "no change", "flat"
    return text, "good" if (d > 0) == higher_is_better else "bad"
