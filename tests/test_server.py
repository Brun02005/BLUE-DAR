from fastapi.testclient import TestClient
from helpers import obs, proximity_pairing

from bluedar.app.server import create_app
from bluedar.classify.rules_engine import load_default_ruleset
from bluedar.pipeline import Session
from bluedar.privacy.pseudonym import Privacy


def test_api_state_label_and_exports():
    rs = load_default_ruleset()
    s = Session(rs, Privacy(name_hinter=rs.name_hint), meta={"session_id": "test"})
    for i in range(3):
        s.ingest(obs(proximity_pairing(), t=i))
    client = TestClient(create_app(s))

    assert "BLUE-DAR" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    state = client.get("/api/state").json()
    entity = state["entities"][0]
    assert entity["label_text"] == "posible auricular" and entity["reasons"][0]["rule"] == "R-APP-07"

    assert client.post(f"/api/entities/{entity['id']}/label", json={"lab_id": "LAB-A01"}).json()["ok"]
    assert client.get("/api/state").json()["meta"]["labels"] == {entity["id"]: "LAB-A01"}
    assert client.post("/api/entities/nope/label", json={"lab_id": "x"}).status_code == 404

    hist = client.get(f"/api/entities/{entity['id']}/history").json()
    assert hist["points"]
    assert "LAB-A01" in client.get("/api/export.csv").text
    assert client.get("/api/export.json").json()["meta"]["session_id"] == "test"

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["packets"] == 3
