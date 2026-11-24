"""API endpoints and the live WebSocket, on a small synthetic CSV (and the fake database from test_db)."""
import logging
import pytest
from fastapi.testclient import TestClient
from pcache.data import generate_requests
from api import main
from pcache import db
from test_db import fake_db  # noqa: F401  (pytest fixture)


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "x_requests.csv"
    generate_requests(regions=("A", "B"), hours=24, n_videos=2000, requests_per_hour=300).to_csv(path, index=False)
    (tmp_path / "x_titles.csv").write_text("region,video_id,title\nA,1,Cats\n")
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.setenv("PCACHE_CSV", str(path))
    with TestClient(main.app) as c:
        c.post("/api/simulate/reset")
        yield c
        c.post("/api/simulate/reset")


def next_of(ws, kind):
    while (m := ws.receive_json())["type"] != kind:
        pass
    return m


def test_health_regions_and_page(client):
    assert client.get("/api/health").json() == {"status": "ok", "source": "csv"}
    assert client.get("/api/regions").json() == {"source": "csv", "regions": ["A", "B"]}
    page = client.get("/")
    assert page.status_code == 200 and "Predictive CDN Cache" in page.text


def test_start_validates_input(client):
    assert client.post("/api/simulate/start", json={"region": "nope"}).status_code == 404
    assert client.post("/api/simulate/start", json={"region": "A", "capacity": 1}).status_code == 422
    assert client.post("/api/simulate/start", json={"region": "A", "speed": 99}).status_code == 422


def test_missing_csv_is_a_clear_503(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PCACHE_CSV", str(tmp_path / "missing.csv"))
    r = client.get("/api/regions")
    assert r.status_code == 503 and "is not a file" in r.json()["detail"]


def test_live_stream_start_pause_reset(client):
    with client.websocket_connect("/ws/live") as ws:
        assert ws.receive_json() == {"type": "state", "status": "idle", "message": "", "config": None,
                                     "total": 0, "history": [], "last": None}
        assert client.post("/api/simulate/start", json={"region": "A", "capacity": 50, "speed": 5}).json() \
            == {"status": "warming"}
        assert next_of(ws, "state")["status"] == "warming"
        first = next_of(ws, "state")             # warm-up done: playing, with the first test hour
        assert first["status"] == "playing" and first["total"] == 12 and first["last"]["hour"] == 12
        hour = next_of(ws, "hour")
        assert hour["hour"] == 13 and hour["index"] == 2
        assert set(hour["hit_rate"]) == {"LRU", "LFU", "Predictive", "Hybrid"}
        assert 0 <= hour["precision"] <= 1 and hour["mae"] >= 0
        assert hour["hybrid_lead"] == pytest.approx(hour["hit_rate"]["Hybrid"] - hour["hit_rate"]["LFU"])
        assert len(hour["top10"]) == 10 and 0 < len(hour["bubbles"]) <= 20
        assert {"pred_trend", "act_trend", "pred_match"} <= set(hour["top10"][0])
        assert any(r["act_trend"] in ("rising", "steady", "fading") for r in hour["top10"])

        assert client.post("/api/simulate/pause").json() == {"status": "paused"}
        assert next_of(ws, "state")["status"] == "paused"
        assert client.post("/api/simulate/reset").json() == {"status": "idle"}
        state = next_of(ws, "state")
        assert state["status"] == "idle" and state["history"] == []


def test_runs_to_finished_and_new_client_gets_history(client):
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        client.post("/api/simulate/start", json={"region": "B", "capacity": 50, "speed": 5})
        while not ((m := ws.receive_json())["type"] == "state" and m["status"] == "finished"):
            pass
    with client.websocket_connect("/ws/live") as ws2:
        s = ws2.receive_json()
        assert s["status"] == "finished" and len(s["history"]) == 12 and s["last"]["hour"] == 23
    # a finished run stays finished until reset
    assert client.post("/api/simulate/start", json={"region": "B", "capacity": 50, "speed": 5}).json() \
        == {"status": "finished"}


def test_titles_from_the_matching_csv(client):
    assert main.titles_and_tags("A")[0] == {1: "Cats"}


def test_regions_from_database(fake_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PGHOST", "db.example")
    with TestClient(main.app) as c:
        assert c.get("/api/regions").json() == {"source": "database", "regions": ["A", "B"]}
        assert c.get("/api/health").json()["source"] == "database"
        assert c.post("/api/simulate/start", json={"region": "A", "capacity": 50}).json() == {"status": "warming"}
        c.post("/api/simulate/reset")


def test_how_it_works_page_served_and_linked(client):
    page = client.get("/how-it-works.html")
    assert page.status_code == 200 and "How it works" in page.text
    assert 'href="how-it-works.html"' in client.get("/").text
    for asset in ("how-it-works.css", "how-it-works.js"):
        assert client.get(f"/{asset}").status_code == 200


def test_dashboard_has_lazy_how_it_works_overlay(client):
    import re
    html = client.get("/").text
    frame = re.search(r'<iframe id="hiw-frame"[^>]*>', html)
    assert '<dialog id="hiw"' in html and frame
    assert " src=" not in frame.group(0)            # loaded only when the overlay first opens
    steps = re.findall(r'data-hiw-step="(s\d+)"', html)
    assert len(steps) >= 8 and set(steps) <= {f"s{i}" for i in range(1, 11)}   # header + one "?" per section


def db_mode(monkeypatch):
    monkeypatch.setenv("PGHOST", "db.example")
    monkeypatch.delenv("PCACHE_TITLES", raising=False)
    monkeypatch.setattr(main, "live", main.Live())   # a lock left over from an earlier test's loop would break


def test_titles_and_tags_from_database(fake_db, monkeypatch):  # noqa: F811
    db_mode(monkeypatch)
    assert main.titles_and_tags("A") == ({1: "Cats", 2: "Dogs", 3: ""}, {1: ["Type 4", "21.0 KB"], 2: ["Type 3"], 3: []})
    assert main.content.title_of(3, {3: ""}) == "Video 3"


def test_missing_titles_table_warns_and_run_works(fake_db, monkeypatch, caplog):  # noqa: F811
    db_mode(monkeypatch)
    monkeypatch.setattr(db, "load_titles", lambda region: (_ for _ in ()).throw(ValueError("Database error: no such table")))
    with caplog.at_level(logging.WARNING):
        assert main.titles_and_tags("A") == ({}, {})
        assert "Video <id>" in caplog.text and "unavailable" in caplog.text
        with TestClient(main.app) as c:
            assert c.post("/api/simulate/start", json={"region": "A", "capacity": 50}).json() == {"status": "warming"}
            c.post("/api/simulate/reset")


def test_videos_without_a_title_are_counted_and_labelled(fake_db, monkeypatch, caplog):  # noqa: F811
    db_mode(monkeypatch)
    with caplog.at_level(logging.WARNING):
        with TestClient(main.app) as c:
            c.post("/api/simulate/start", json={"region": "A", "capacity": 50})
            c.post("/api/simulate/reset")
    ids = set(db.load_region("A")["video_id"])
    n = len(ids - {1, 2})   # only videos 1 and 2 have a title; video 3's is NULL
    assert 3 in ids and f"{n} of {len(ids)} videos in A have no title" in caplog.text
    assert main.content.title_of(999, {1: "Cats"}) == "Video 999"


def test_pcache_titles_beats_the_database(fake_db, monkeypatch, tmp_path):  # noqa: F811
    db_mode(monkeypatch)
    f = tmp_path / "t.csv"
    f.write_text("region,video_id,title\nA,1,FromFile\n")
    monkeypatch.setenv("PCACHE_TITLES", str(f))
    monkeypatch.setattr(db, "load_titles", lambda region: pytest.fail("DB titles must not be queried"))
    assert main.titles_and_tags("A")[0] == {1: "FromFile"}


def test_csv_falls_back_to_cachemon_titles_beside_requests_hourly(tmp_path, monkeypatch):
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PCACHE_TITLES", raising=False)
    monkeypatch.setenv("PCACHE_CSV", str(tmp_path / "requests_hourly.csv"))
    assert main.titles_and_tags("A") == ({}, {})
    (tmp_path / "cachemon_titles.csv").write_text("region,video_id,title,content_type,size_bytes\nA,1,Cats,4,21000\n")
    assert main.titles_and_tags("A") == ({1: "Cats"}, {1: ["Type 4", "21.0 KB"]})
