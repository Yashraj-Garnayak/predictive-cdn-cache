import pandas as pd
import pytest
from scripts.prepare_cachemon import main, region_name

HEADER = ("timestamp,cacheKey,OpType,objectSize,responseSize,responseHeaderSize,rangeStart,rangeEnd,"
          "TTL,SamplingRate,cache_hit,item_value,RequestHandler,cdn_content_type_id,vip_type")
T0 = 1678863509425  # ms, first timestamp of the real reag trace
HOUR = 3_600_000
# (offset ms, key): key A requested 3x, B 2x, C 1x; spans hours 0, 1 and 2
REQUESTS = [(0, "A"), (1000, "B"), (HOUR + 5, "A"), (HOUR + 9, "C"), (2 * HOUR, "A"), (2 * HOUR + 1, "B")]
# key -> (objectSize, responseSize, cdn_content_type_id); A has no objectSize (-1), B has no type ("-")
OBJECTS = {"A": (-1, 246307, "9"), "B": (25568, 26063, "-"), "C": (100, 120, "2")}


def write_trace(path, compress=False):
    lines = [HEADER] + [f"{T0 + dt},00678133{k}000000,1,{OBJECTS[k][0]},{OBJECTS[k][1]},547,-1,-1,1209600,"
                        f"0.0001,0,1,1000,{OBJECTS[k][2]},2000" for dt, k in REQUESTS]
    data = ("\n".join(lines) + "\n").encode()
    if compress:
        zstd = pytest.importorskip("compression.zstd")
        data = zstd.compress(data)
    path.write_bytes(data)


def test_convert_single_trace(tmp_path):
    trace, out = tmp_path / "reag0c01_20230315_20230322_0.2000.csv.zst", tmp_path / "out.csv"
    write_trace(trace, compress=True)
    main([str(trace), "--top-objects", "2", "--out", str(out)])
    df = pd.read_csv(out)
    assert list(df.columns) == ["region", "hour", "video_id"]
    assert set(df["region"]) == {"CDN-edge"}           # trace has no region column
    assert len(df) == 5                                  # C is not in the top 2 objects
    assert list(df["hour"]) == [0, 0, 1, 2, 2]
    assert df["video_id"].nunique() == 2
    a = df["video_id"].iloc[0]                           # first request is key A
    assert list(df["video_id"] == a) == [True, False, True, True, False]

    # --out has no 'requests' in its name, so object details go to out_titles.csv
    info = pd.read_csv(tmp_path / "out_titles.csv", dtype={"content_type": str})
    info = info.set_index("title")
    assert list(info.columns) == ["region", "video_id", "content_type", "size_bytes"]
    assert set(info.index) == {"00678133A", "00678133B"}        # zero padding removed; C not kept
    assert info.loc["00678133A", "video_id"] == a
    assert info.loc["00678133A", "size_bytes"] == 246307           # no objectSize -> responseSize
    assert info.loc["00678133B", "size_bytes"] == 25568
    assert info.loc["00678133A", "content_type"] == "9"
    assert pd.isna(info.loc["00678133B", "content_type"])          # '-' in the trace = unknown


def test_max_rows_and_clusters(tmp_path):
    t1, t2, out = tmp_path / "reag0c01_x.csv", tmp_path / "rnha0c01_x.csv", tmp_path / "out.csv"
    write_trace(t1); write_trace(t2)
    main([str(t1), str(t2), "--max-rows", "3", "--out", str(out)])
    df = pd.read_csv(out)
    assert df.groupby("region").size().to_dict() == {"CDN-edge-eag": 3, "CDN-edge-nha": 3}
    assert region_name(t1, 1) == "CDN-edge"
