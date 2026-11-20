"""Convert Meta CDN request traces (cacheMon cache_dataset) to pcache format.

Source: https://github.com/cacheMon/cache_dataset (CC BY 4.0), Meta CDN traces 2023,
originally released via CacheLib. Files: cache_dataset_txt/2023_metaCDN/<cluster>..._.csv.zst

Each file (one CDN edge cluster, 7 days) becomes one region; a single file becomes
the region "CDN-edge". Each cacheKey stands in for a video. Output columns: region,hour,video_id
Object details are written alongside: region,video_id,title,content_type,size_bytes
(title = the cacheKey without its zero padding, e.g. 00678133533).

Files are streamed in chunks twice (count objects, then write their requests), so the
~46 GB of uncompressed CSV never has to fit in memory or on disk.
"""
from __future__ import annotations
import argparse, io, logging
from pathlib import Path
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
COLUMNS = ["timestamp", "cacheKey"]  # timestamp is in milliseconds
INFO_COLUMNS = COLUMNS + ["objectSize", "responseSize", "cdn_content_type_id"]
CHUNK = 2_000_000


def open_trace(path: Path):
    """Open a .csv or .csv.zst trace as a text stream."""
    if path.suffix != ".zst":
        return open(path, "rt", newline="")
    try:
        from compression import zstd  # Python 3.14+
        raw = zstd.open(path, "rb")
    except ImportError:
        import zstandard
        raw = zstandard.ZstdDecompressor().stream_reader(open(path, "rb"))
    return io.TextIOWrapper(raw, encoding="utf-8", newline="")


def read_chunks(path: Path, max_rows: int | None, columns: list[str] = COLUMNS):
    """Yield (chunk, key_hash) pairs; chunk holds `columns`, key_hash is a uint64 per row."""
    seen = 0
    dtypes = {"timestamp": "int64", "cacheKey": "str", "cdn_content_type_id": "str"}
    with open_trace(path) as f:
        for chunk in pd.read_csv(f, usecols=columns, dtype={c: dtypes[c] for c in columns if c in dtypes},
                                 chunksize=CHUNK):
            if max_rows is not None:
                chunk = chunk.iloc[: max_rows - seen]
            # 64-bit hash of the (long, hex) key keeps memory small; collisions are negligible
            yield chunk, pd.util.hash_array(chunk["cacheKey"].to_numpy(object))
            seen += len(chunk)
            if max_rows is not None and seen >= max_rows:
                return


def _merge(keys: np.ndarray, counts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    uniq, inv = np.unique(keys, return_inverse=True)
    return uniq, np.bincount(inv, weights=counts).astype(np.int64)


def top_objects(path: Path, top: int, max_rows: int | None) -> tuple[np.ndarray, int]:
    """Pass 1: hashes of the `top` most-requested objects (sorted), and the first timestamp."""
    keys, counts, start = np.empty(0, np.uint64), np.empty(0, np.int64), None
    for chunk, h in read_chunks(path, max_rows):
        ts = chunk["timestamp"].to_numpy()
        start = ts.min() if start is None else min(start, ts.min())
        u, c = np.unique(h, return_counts=True)
        keys, counts = _merge(np.concatenate([keys, u]), np.concatenate([counts, c]))
    if start is None:
        raise ValueError(f"{path} has no requests")
    best = np.argsort(-counts, kind="stable")[:top]
    log.info("%s: %d distinct objects, top %d hold %.1f%% of requests",
             path.name, len(keys), len(best), 100 * counts[best].sum() / counts.sum())
    return np.sort(keys[best]), int(start)


def object_id(key: str) -> str:
    """Readable object id: cacheKeys are short ids padded with zeros, e.g. 00678133533000... -> 00678133533."""
    return key.rstrip("0") or "0"


def _object_info(parts: list[pd.DataFrame]) -> pd.DataFrame:
    """One row per video: readable id, content type and size (objectSize, else responseSize)."""
    info = pd.concat(parts).groupby("video_id").agg(
        key=("cacheKey", "first"), content_type=("cdn_content_type_id", "first"),
        object_size=("objectSize", "max"), response_size=("responseSize", "max"))
    size = info["object_size"].where(info["object_size"] > 0, info["response_size"])
    return pd.DataFrame({"video_id": info.index, "title": info["key"].map(object_id).to_numpy(),
                         "content_type": info["content_type"].replace("-", "").to_numpy(),
                         "size_bytes": size.clip(lower=0).astype("int64").to_numpy()})


def convert(path: Path, region: str, top: int, max_rows: int | None, out) -> tuple[int, pd.DataFrame]:
    """Pass 2: write region,hour,video_id rows for requests to the top objects; return object info."""
    keep, start = top_objects(path, top, max_rows)
    written, parts = 0, []
    for chunk, h in read_chunks(path, max_rows, INFO_COLUMNS):
        pos = np.searchsorted(keep, h).clip(max=len(keep) - 1)
        hit = keep[pos] == h
        kept = chunk[hit].assign(video_id=pos[hit])
        hours = (kept["timestamp"].to_numpy() - start) // 3_600_000
        pd.DataFrame({"region": region, "hour": hours, "video_id": kept["video_id"].to_numpy()}).to_csv(
            out, header=False, index=False)
        parts.append(kept.groupby("video_id").agg({"cacheKey": "first", "cdn_content_type_id": "first",
                                                   "objectSize": "max", "responseSize": "max"}).reset_index())
        written += len(kept)
    log.info("%s -> %s: %d requests", path.name, region, written)
    return written, _object_info(parts).assign(region=region)


def region_name(path: Path, n_files: int) -> str:
    """'CDN-edge' for a single trace, else 'CDN-edge-<cluster>' (e.g. reag0c01_... -> eag)."""
    if n_files == 1:
        return "CDN-edge"
    return f"CDN-edge-{path.name.split('_')[0].removeprefix('r').split('0c')[0]}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="trace files (default: data/raw/cachemon/*.csv.zst)")
    ap.add_argument("--top-objects", type=int, default=20000)
    ap.add_argument("--max-rows", type=int, help="read only the first N rows of each file (quick sample)")
    ap.add_argument("--out", type=Path, default=Path("data/cachemon_requests.csv"))
    ap.add_argument("--titles-out", type=Path,
                    help="object ids/types/sizes (default: --out with 'requests' -> 'titles')")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    files = a.files or sorted(Path("data/raw/cachemon").glob("*.csv.zst"))
    if not files:
        ap.error("no trace files found; download them into data/raw/cachemon/ first")
    titles_out = a.titles_out or a.out.with_name(a.out.name.replace("requests", "titles"))
    if titles_out == a.out:
        titles_out = a.out.with_name(a.out.stem + "_titles.csv")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    total, infos = 0, []
    with open(a.out, "w", newline="") as out:
        out.write("region,hour,video_id\n")
        for path in files:
            n, info = convert(path, region_name(path, len(files)), a.top_objects, a.max_rows, out)
            total, infos = total + n, infos + [info]
    pd.concat(infos)[["region", "video_id", "title", "content_type", "size_bytes"]].to_csv(titles_out, index=False)
    print(f"wrote {total:,} requests to {a.out} and object details to {titles_out}")


if __name__ == "__main__":
    main()
