import json
from datetime import timedelta

from helpers import T0, find_my, name, obs, proximity_pairing

from bluedar.classify.rules_engine import load_default_ruleset
from bluedar.cli import main
from bluedar.pipeline import Session
from bluedar.privacy.pseudonym import Privacy
from bluedar.store.jsonl_log import JsonlWriter, from_record, read_jsonl, to_record


def make_session(writer=None, **kw):
    rs = load_default_ruleset()
    clock = kw.pop("clock", None)
    return Session(rs, Privacy(name_hinter=rs.name_hint), writer, clock=clock, **kw)


def test_jsonl_roundtrip_preserves_redaction(tmp_path):
    p = Privacy().apply(obs(proximity_pairing(), name("AirPods de Ana"), rssi=-48))
    rec = to_record(p)
    back = from_record(json.loads(json.dumps(rec)))
    assert back.ad == p.ad and back.rssi == -48 and back.has_name
    assert "Ana" not in json.dumps(rec)


def test_live_observations_require_privacy():
    s = Session(load_default_ruleset())
    try:
        s.ingest(obs())
    except RuntimeError:
        pass
    else:
        raise AssertionError("debería exigir la capa de privacidad")


def test_presence_new_and_gone():
    now = {"t": T0}
    s = make_session(clock=lambda: now["t"], absence_s=30)
    e = s.ingest(obs(find_my()))
    assert e.present and s.events[-1]["event"] == "nuevo"
    now["t"] = T0 + timedelta(seconds=31)
    s.tick()
    assert not e.present and s.events[-1]["event"] == "ausente"
    s.ingest(obs(find_my(), t=40))
    assert e.present and s.events[-1]["event"] == "reaparece"


def test_spam_alert_with_many_proximity_pairing_addresses():
    s = make_session()
    for i in range(8):
        s.ingest(obs(proximity_pairing(), address=f"4A:00:00:00:00:{i:02X}", t=i * 0.5))
    assert s.spam_active
    snap = s.snapshot()
    assert any("spam" in w for e in snap["entities"] for w in e["warnings"])


def test_no_real_address_reaches_disk(tmp_path):
    path = tmp_path / "s.jsonl"
    writer = JsonlWriter(path)
    s = make_session(writer)
    s.ingest(obs(proximity_pairing(), address="4A:11:22:33:44:55"))
    writer.close()
    text = path.read_text()
    assert "4A:11:22:33:44:55" not in text and "4a1122334455" not in text.lower()


def test_export_from_capture(tmp_path, capsys):
    path = tmp_path / "s.jsonl"
    writer = JsonlWriter(path)
    s = make_session(writer)
    for i in range(4):
        s.ingest(obs(proximity_pairing(), t=i))
        s.ingest(obs(find_my(), address="C1:00:00:00:00:01", address_kind="random_static", t=i))
    writer.close()
    assert len(list(read_jsonl(path))) == 8

    out = tmp_path / "out.csv"
    assert main(["export", str(path), "-o", str(out)]) == 0
    csv_text = out.read_text(encoding="utf-8")
    assert "posible auricular" in csv_text and "AirPods Pro (0x0e20)" in csv_text
    assert "Find My" in csv_text

    assert main(["stats", str(path)]) == 0
    assert "0x07(modelo 0e20)" in capsys.readouterr().out
