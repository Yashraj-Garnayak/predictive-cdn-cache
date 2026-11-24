"""Turning simulation results into what the live page shows (moved from the old Streamlit dashboard)."""
from pathlib import Path
import pandas as pd
from api import content

TITLES = {1: "Berlin", 2: "Python (programming language)"}
# predicted ranks 1 > 3 > 2; actual ranks 2 > 1 > 4
PRED = pd.Series({1: 9.0, 3: 5.0, 2: 1.5})
ACT = pd.Series({2: 12, 1: 8, 4: 3})


def test_titles_path_and_lookup(tmp_path):
    assert content.titles_path("data/wiki_requests.csv") == Path("data/wiki_titles.csv")
    f = tmp_path / "wiki_titles.csv"
    pd.DataFrame({"region": ["Frankfurt", "Mumbai"], "video_id": [1, 1], "title": ["Berlin", "Mumbai"]}).to_csv(f, index=False)
    titles = content.read_titles(f)
    assert titles == {"Frankfurt": {1: "Berlin"}, "Mumbai": {1: "Mumbai"}}
    assert content.read_titles(tmp_path / "missing.csv") == {}
    assert content.title_of(1, titles["Frankfurt"]) == "Berlin"
    assert content.title_of(7, {}) == "Video 7"  # synthetic data has no titles


def test_bubble_data_marks_predicted_videos():
    data = content.bubble_data(PRED, ACT, TITLES, n=2)
    assert [d["id"] for d in data] == [2, 1]          # top 2 by actual requests
    assert data[0] == {"id": 2, "label": "Video 2", "title": "Python (programming language)", "actual": 12, "predicted": 1.5,
                       "hit": False, "trend": None, "tags": [], "type": None, "size": None, "region": ""}  # no history / details yet
    assert data[1]["hit"] is True                      # 1 is among the model's top 2 picks
    assert content.bubble_data(PRED, ACT, {}, n=3)[2] == {"id": 4, "label": "Video 4", "title": "Video 4", "actual": 3, "predicted": 0.0,
                                                          "hit": False, "trend": None, "tags": [], "type": None, "size": None, "region": ""}
    tagged = content.bubble_data(PRED, ACT, TITLES, n=2, trend_of={2: "rising"}, tags={2: ["Type 3", "21.9 KB"]})
    assert tagged[0]["trend"] == "rising" and tagged[0]["tags"] == ["Type 3", "21.9 KB"]
    assert tagged[1]["trend"] is None and tagged[1]["tags"] == []


def test_trend_tags():
    assert content.trend(30, 10) == "rising"           # 3x the recent average
    assert content.trend(11, 10) == "steady"
    assert content.trend(3, 10) == "fading"
    assert content.trend(2, 1) == "steady"             # tiny counts (1 -> 2) are not called a surge
    # oldest -> newest; the last series is the current hour
    recent = [pd.Series({1: 10, 2: 10, 3: 10}), pd.Series({1: 10, 2: 10, 3: 10}),
              pd.Series({1: 10, 2: 10, 3: 10}), pd.Series({1: 40, 2: 10, 3: 2})]
    assert content.trends(recent, [1, 2, 3, 4]) == {1: "rising", 2: "steady", 3: "fading", 4: "steady"}
    old = [pd.Series({1: 1000})] + recent               # only the previous TREND_HOURS hours count
    assert content.trends(old, [1]) == {1: "rising"}
    assert content.trends(recent[-1:], [1]) == {}      # no history yet -> no tag


def test_object_info_tags(tmp_path):
    assert [content.format_size(b) for b in (0, -1, 512, 1536, 21927, 52_428_800, 1_933_047_221)] == \
        ["", "", "512 B", "1.5 KB", "21.9 KB", "52.4 MB", "1.9 GB"]
    f = tmp_path / "cachemon_titles.csv"
    pd.DataFrame({"region": ["CDN-edge", "CDN-edge"], "video_id": [0, 1], "title": ["00678133533", "0067"],
                  "content_type": ["3", None], "size_bytes": [21927, 0]}).to_csv(f, index=False)
    assert content.read_object_info(f) == {"CDN-edge": {0: ["Type 3", "21.9 KB"], 1: []}}
    assert content.read_titles(f) == {"CDN-edge": {0: "00678133533", 1: "0067"}}
    wiki = tmp_path / "wiki_titles.csv"                 # titles only -> no tags
    pd.DataFrame({"region": ["Frankfurt"], "video_id": [1], "title": ["Berlin"]}).to_csv(wiki, index=False)
    assert content.read_object_info(wiki) == {}
    assert content.read_object_info(tmp_path / "missing.csv") == {}


def test_table_shows_tags():
    rows = content.table_rows(PRED, ACT, TITLES, k=2, trend_of={1: "fading", 2: "rising"}, tags={2: ["Type 7"]})
    assert rows[0]["act_trend"] == "rising" and rows[0]["act_tags"] == ["Type 7"]   # actual #1 is video 2
    assert rows[0]["pred_trend"] == "fading" and rows[0]["pred_tags"] == []        # predicted #1 is video 1


def test_table_rows_flag_matches():
    rows = content.table_rows(PRED, ACT, TITLES, k=3)
    assert [r["pred_title"] for r in rows] == ["Berlin", "Video 3", "Python (programming language)"]
    assert [r["pred_match"] for r in rows] == [True, False, True]
    assert [r["act_match"] for r in rows] == [True, True, False]
    short = content.table_rows(PRED.head(1), ACT, TITLES, k=2)  # model predicted fewer than k videos
    assert short[1]["pred_title"] == "" and short[1]["pred_count"] is None


def test_bubble_label_chip_and_tooltip_fields():
    """Everything the bubble label, type chip and hover tooltip show comes in the bubble data."""
    d = content.bubble_data(PRED, ACT, TITLES, n=2, trend_of={2: "rising"}, tags={2: ["Type 4", "21.0 KB"]}, region="eag")[0]
    assert d["label"] == "Video 2"                                   # main text is always "Video <id>"
    assert d["type"] == "Type 4" and d["size"] == "21.0 KB"          # chip text, tooltip size
    assert (d["actual"], d["predicted"], d["hit"], d["trend"], d["region"]) == (12, 1.5, False, "rising", "eag")


def test_bubble_without_title_row_has_no_type_or_size():
    d = content.bubble_data(PRED, ACT, {}, n=3, tags={})[2]            # video 4 has no row in the titles table
    assert d["label"] == "Video 4" and d["type"] is None and d["size"] is None
    only_size = content.bubble_data(PRED, ACT, {}, n=1, tags={2: ["21.0 KB"]})[0]   # NULL content_type
    assert only_size["type"] is None and only_size["size"] == "21.0 KB"


def test_format_size_units():
    assert [content.format_size(n) for n in (0, None, 512, 1536, 21000, 2_500_000, 3_100_000_000)] == \
        ["", "", "512 B", "1.5 KB", "21.0 KB", "2.5 MB", "3.1 GB"]


def test_tags_capitalised_type():
    df = pd.DataFrame({"video_id": [1], "title": ["a"], "content_type": [4], "size_bytes": [21000.0]})
    assert content.titles_and_tags_from(df)[1] == {1: ["Type 4", "21.0 KB"]}
