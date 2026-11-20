import base64, json, sys
from pathlib import Path
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
from ui import content, layout, theme  # noqa: E402

PAGE = str(ROOT / "dashboard" / "pages" / "live_view.py")
WIKI = ROOT / "data" / "wiki_requests.csv"
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
    assert data[0] == {"id": 2, "title": "Python (programming language)", "actual": 12, "predicted": 1.5, "hit": False}
    assert data[1]["hit"] is True                      # 1 is among the model's top 2 picks
    assert content.bubble_data(PRED, ACT, {}, n=3)[2] == {"id": 4, "title": "Video 4", "actual": 3, "predicted": 0.0, "hit": False}


def test_table_rows_flag_matches():
    rows = content.table_rows(PRED, ACT, TITLES, k=3)
    assert [r["pred_title"] for r in rows] == ["Berlin", "Video 3", "Python (programming language)"]
    assert [r["pred_match"] for r in rows] == [True, False, True]
    assert [r["act_match"] for r in rows] == [True, True, False]
    short = content.table_rows(PRED.head(1), ACT, TITLES, k=2)  # model predicted fewer than k videos
    assert short[1]["pred_title"] == "" and short[1]["pred_count"] is None


def test_delta():
    assert content.delta(5, None, "{:+.0f}") is None
    assert content.delta(5, 3, "{:+.0f}") == ("+2", "good")
    assert content.delta(5, 3, "{:+.0f}", higher_is_better=False) == ("+2", "bad")
    assert content.delta(3, 3, "{:+.0f}") == ("no change", "flat")
    assert content.delta(0.351, 0.350, "{:+.2f}") == ("no change", "flat")  # too small to show


def test_theme_css():
    css = theme.page_css()
    assert css.startswith("<style>") and "__CARDS__" not in css
    assert all(f".st-key-{k}" in css for k in theme.CARD_KEYS)
    assert theme.POLICY_COLORS["Hybrid"] in theme.css_vars() and "--green: #30D158" in theme.css_vars()


def test_html_builders_escape_and_encode():
    cards = layout.metric_cards_html([{"label": "A <b>", "value": "7", "tip": "t", "accent": "#fff", "delta": ("+1", "good")}])
    assert "A &lt;b&gt;" in cards and 'lv-delta good' in cards
    table = layout.table_html([{"rank": 1, "pred_title": "<x>", "pred_count": 1.0, "pred_match": True,
                                "act_title": "y", "act_count": 2, "act_match": False}], hour=5)
    assert "&lt;x&gt;" in table and "lv-pip miss" in table and "Hour 5" in table
    data = [{"id": 1, "title": "Café"}]
    assert json.loads(base64.b64decode(layout.encode_bubbles(data))) == data
    bar = layout.progress_html(3, 12, 30, "playing", prev_done=2)
    assert "--to:25.00%" in bar and "--from:16.67%" in bar


def test_bubble_page_is_constant_and_themed():
    html = layout._bubbles_page()
    assert "/*THEME*/" not in html and "--green: #30D158" in html and "d3.min.js" in html
    assert html == layout._bubbles_page()  # same HTML every hour, so the iframe is never reloaded


def test_hit_rate_chart_uses_policy_colours():
    spec = layout.hit_rate_chart_spec([{"hour": 1, "LRU": 1, "LFU": 2, "Predictive": 3, "Hybrid": 4}]).to_dict()
    scale = spec["layer"][0]["encoding"]["color"]["scale"]
    assert dict(zip(scale["domain"], scale["range"])) == theme.POLICY_COLORS


def _run_page(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception
    at.button(key="lv_start").click().run()  # fast-forwards warm-up, shows the first test hour
    assert not at.exception
    return at


def _page_html(at: AppTest) -> str:
    return "".join(el.value for el in at.get("html"))


def test_page_synthetic():
    at = _run_page(AppTest.from_file(PAGE, default_timeout=120))
    html = _page_html(at)
    for label in ["Model picks that were right (top 10)", "Average guess error (views)",
                  "Hybrid&#x27;s lead over LFU", "Hybrid hit rate"]:
        assert label in html
    assert "Video " in html                    # no titles for synthetic data
    assert "pcache-bubble-data" in html and "lv-table" in html


@pytest.mark.skipif(not WIKI.exists(), reason="run scripts/prepare_wikipedia.py first")
def test_page_wikipedia():
    at = AppTest.from_file(PAGE, default_timeout=180)
    at.run()
    at.radio(key="lv_source").set_value("CSV file")
    at = _run_page(at)
    html = _page_html(at)
    assert "Wikipedia pageviews" in html
    rows = html.split("<tbody>")[1]
    assert rows.count("Video ") < 5            # real article titles, not ids
