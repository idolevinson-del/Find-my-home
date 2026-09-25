import shutil

import pytest
from fastapi.testclient import TestClient

from app import config, pipeline
from app.web.server import create_app
from tests.conftest import ROOT, FixtureYad2


@pytest.fixture
def client(conn, settings, feed, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    shutil.copy(ROOT / "config.yaml", cfg)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)])
    return TestClient(create_app(conn))


def test_dashboard_flow(client):
    assert client.get("/").status_code == 200
    rows = client.get("/api/listings").json()
    assert {r["source_id"] for r in rows} == {"florentin1", "levontin1"}
    r = rows[0]
    assert r["is_new"] and r["match_score"] is not None and r["score_breakdown"]

    assert client.post(f"/api/listings/{r['id']}/status", json={"status": "SAVED"}).json()["ok"]
    assert [x["id"] for x in client.get("/api/listings?view=saved").json()] == [r["id"]]
    assert r["id"] not in [x["id"] for x in client.get("/api/listings").json()]
    assert client.post(f"/api/listings/{r['id']}/status", json={"status": "BOGUS"}).status_code == 400

    s = client.get("/api/summary").json()
    assert s["total"] == 1 and s["saved"] == 1


def test_settings_roundtrip(client):
    out = client.put("/api/settings", json={"search": {"max_price": 11000}}).json()
    assert out["search"]["max_price"] == 11000 and out["search"]["min_rooms"] == 4
    assert client.get("/api/settings").json()["search"]["max_price"] == 11000
    # the 11,900 Levontin listing no longer passes
    assert {r["source_id"] for r in client.get("/api/listings").json()} == {"florentin1"}
