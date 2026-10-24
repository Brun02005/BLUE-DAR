import math
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from helpers import T0, obs, proximity_pairing

from bluedar.app.server import create_app
from bluedar.classify.rules_engine import load_default_ruleset
from bluedar.pipeline import Session
from bluedar.positioning.room import NodeConfig, Room
from bluedar.positioning.simulate import run as simulate
from bluedar.positioning.trilateration import Range, make_range, rssi_to_distance, trilaterate
from bluedar.privacy.pseudonym import Privacy
from bluedar.store.jsonl_log import to_record

NODES = {"local": (0.0, 0.0), "b": (5.0, 0.0), "c": (2.5, 4.0)}


def room(tmp_path=None):
    nodes = {k: NodeConfig(k, x, y) for k, (x, y) in NODES.items()}
    r = Room(5.0, 4.0, nodes, tmp_path / "room.yaml" if tmp_path else None)
    r.save()
    return r


def ideal_rssi(node, x, y, ref=-59.0, n=2.5):
    return ref - 10 * n * math.log10(max(0.2, math.hypot(x - node[0], y - node[1])))


def test_rssi_distance_model():
    assert rssi_to_distance(-59, -59, 2.5) == pytest.approx(1.0)
    assert rssi_to_distance(-84, -59, 2.5) == pytest.approx(10.0)


def test_noiseless_trilateration_is_exact():
    tx, ty = 3.1, 1.7
    ranges = [make_range(k, x, y, ideal_rssi((x, y), tx, ty), -59, 2.5, 0) for k, (x, y) in NODES.items()]
    fix = trilaterate(ranges, 5.0, 4.0)
    assert fix is not None
    assert math.hypot(fix.x - tx, fix.y - ty) < 0.05


def test_needs_three_nodes_and_non_collinear_geometry():
    two = [Range("a", 0, 0, 1, 0.5), Range("b", 5, 0, 4, 0.5)]
    assert trilaterate(two, 5, 4) is None
    collinear = [Range("a", 0, 0, 2, 0.5), Range("b", 2, 0, 0.5, 0.5), Range("c", 4, 0, 2, 0.5)]
    fix = trilaterate(collinear, 5, 4)
    assert fix is None or fix.radius > 0.5  # alineados: la dirección perpendicular no está determinada


def test_simulation_reports_baseline_and_degrades_with_noise():
    r = room()
    low, high = simulate(r, 2.0, trials=200), simulate(r, 8.0, trials=200)
    assert low.median_m < high.median_m
    assert low.median_m < low.center_median_m  # con poco ruido le gana a "decir el centro"
    assert high.coverage > 0.5  # el radio informado no es optimista


def test_room_validation(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("room: {width_m: 3, height_m: 3}\nnodes:\n  a: {x: 5, y: 1}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Room.load(path)


def make_session(tmp_path):
    rs = load_default_ruleset()
    now = {"t": T0}
    s = Session(rs, Privacy(name_hinter=rs.name_hint), room=room(tmp_path), clock=lambda: now["t"])
    return s, now


def feed(session, address, tx, ty, packets=5):
    for i in range(packets):
        for node_id, pos in NODES.items():
            o = obs(proximity_pairing(), address=address, rssi=round(ideal_rssi(pos, tx, ty)), t=i * 0.5)
            o.node = node_id
            session.ingest(o)


def test_only_lab_entities_are_located(tmp_path):
    s, now = make_session(tmp_path)
    feed(s, "4A:00:00:00:00:01", 1.0, 1.0)
    feed(s, "4A:00:00:00:00:02", 4.0, 3.0)
    now["t"] = T0 + timedelta(seconds=3)
    assert s.positions() == []  # sin LAB-ID no se ubica a nadie
    own = s.privacy.pseudonym("4A:00:00:00:00:01")
    s.label(own, "LAB-A01")
    positions = s.positions()
    assert [p["lab_id"] for p in positions] == ["LAB-A01"]
    p = positions[0]
    assert p["status"] == "estimada" and math.hypot(p["x"] - 1.0, p["y"] - 1.0) < 0.6


def test_stale_nodes_do_not_count(tmp_path):
    s, now = make_session(tmp_path)
    feed(s, "4A:00:00:00:00:01", 1.0, 1.0)
    s.label(s.privacy.pseudonym("4A:00:00:00:00:01"), "LAB-A01")
    now["t"] = T0 + timedelta(seconds=60)
    assert s.positions() == [] or s.positions()[0]["x"] is None


def test_calibration_sets_reference_and_persists(tmp_path):
    s, now = make_session(tmp_path)
    feed(s, "4A:00:00:00:00:01", 1.0, 0.0)  # a 1 m de "local"
    own = s.privacy.pseudonym("4A:00:00:00:00:01")
    with pytest.raises(ValueError):
        s.calibrate(own, "local", 1.0)  # sin LAB-ID no se calibra
    s.label(own, "LAB-A01")
    result = s.calibrate(own, "local", 1.0)
    assert result["ref_dbm"] == pytest.approx(-59, abs=1.5)
    assert Room.load(tmp_path / "room.yaml").nodes["local"].calibrated


def test_remote_node_api(tmp_path):
    s, _ = make_session(tmp_path)
    client = TestClient(create_app(s))
    reg = client.post("/api/nodes/register", json={"node_id": "b"}).json()
    assert reg["key"] == s.privacy.key_hex
    assert client.post("/api/nodes/register", json={"node_id": "local"}).status_code == 400

    # El nodo pseudonimiza con la clave del hub: mismo pseudónimo que el escáner local.
    node_privacy = Privacy(key=bytes.fromhex(reg["key"]))
    record = to_record(node_privacy.apply(obs(proximity_pairing(), address="4A:00:00:00:00:09")))
    url = "/api/nodes/b/observations"
    assert client.post(url, json={"records": [record]}).status_code == 401
    ok = client.post(url, json={"records": [record]}, headers={"Authorization": f"Bearer {reg['token']}"})
    assert ok.json() == {"accepted": 1}
    entity = s.tracker.entities[s.privacy.pseudonym("4A:00:00:00:00:09")]
    assert "b" in entity.node_rssi
    bad = client.post(url, json={"records": [{"v": 9}]}, headers={"Authorization": f"Bearer {reg['token']}"})
    assert bad.status_code == 400
    assert any(n["id"] == "b" and n["remote"] for n in client.get("/api/state").json()["nodes"])


def test_replay_session_rejects_remote_nodes():
    s = Session(load_default_ruleset(), virtual_time=True)
    with pytest.raises(RuntimeError):
        s.register_node("b")
