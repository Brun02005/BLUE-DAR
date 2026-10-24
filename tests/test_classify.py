import pytest
from helpers import appearance, fast_pair, find_my, nearby_info, obs, proximity_pairing

from bluedar.classify.evidence import EntityEvidence
from bluedar.classify.rules_engine import load_default_ruleset, parse_rules
from bluedar.decode.ad_structures import decode


def classify(*packets):
    rs = load_default_ruleset()
    agg = EntityEvidence()
    has_payload = False
    for p in packets:
        agg.add(rs.evaluate(p, decode(p)), p.t)
        has_payload = has_payload or any(s.type != 0x01 for s in p.ad)
    return agg.classify(len(packets), has_payload)


def test_rules_file_is_valid():
    rs = load_default_ruleset()
    assert {r.id for r in rs.rules} >= {"R-APP-07", "R-FP-MODEL", "R-COD", "R-NAME"}
    assert all(r.validated is None for r in rs.rules)  # nada validado todavía


def test_airpods_format_is_declared_not_confirmed():
    c = classify(*[obs(proximity_pairing(), t=i) for i in range(3)])
    assert c.label == "auricular" and c.basis == "declarado"
    assert c.confidence == "media"  # ingeniería inversa, no validada: nunca "alta"
    assert c.model == "AirPods Pro (0x0e20)"


def test_single_packet_is_low_confidence():
    assert classify(obs(proximity_pairing())).confidence == "baja"


def test_untabulated_model_keeps_type_without_name():
    c = classify(*[obs(proximity_pairing(bytes.fromhex("1420")), t=i) for i in range(3)])
    assert c.label == "auricular" and c.model == "no tabulado (0x1420)"


def test_changing_models_warns_possible_spoofing():
    c = classify(obs(proximity_pairing(bytes.fromhex("0e20"))), obs(proximity_pairing(bytes.fromhex("1420")), t=1))
    assert any("falsificación" in w for w in c.warnings)


def test_iphone_is_unknown_not_audio():
    c = classify(*[obs(nearby_info(), t=i) for i in range(5)])
    assert c.label == "desconocido" and "Apple" in c.family


def test_find_my_does_not_claim_type():
    c = classify(*[obs(find_my(), t=i) for i in range(5)])
    assert c.label == "desconocido" and "Find My" in c.family


def test_find_my_airpods_hint_is_family_not_audio_claim():
    c = classify(*[obs(find_my(status=0x18), t=i) for i in range(5)])
    assert c.label == "desconocido"  # pista sin validar: no se declara auricular
    assert "AirPods" in c.family and "separado" in c.family
    assert "no cuál dispositivo" in c.reasons[0]["detail"]


def test_audio_plus_non_audio_on_same_address_is_insufficient():
    c = classify(obs(proximity_pairing()), obs(nearby_info(), t=1))
    assert c.label == "insuficiente"


def test_appearance_standard_reaches_high_confidence():
    c = classify(*[obs(appearance(0x0941), t=i) for i in range(3)])
    assert c.label == "auricular" and c.confidence == "alta" and c.basis == "declarado"


def test_contradictory_types():
    c = classify(obs(appearance(0x0941)), obs(appearance(0x0841), t=1))
    assert c.label == "insuficiente"


def test_fast_pair_without_table_is_insufficient():
    c = classify(*[obs(fast_pair(bytes.fromhex("a1b2c3")), t=i) for i in range(3)])
    assert c.label == "insuficiente" and "Fast Pair" in c.family


def test_name_hint_is_hypothesis():
    p = obs(t=0)
    p.name_hint = "parlante:party"
    c = classify(p, obs(t=1), obs(t=2))
    assert c.label == "parlante" and c.basis == "hipótesis" and c.confidence == "baja"


def test_empty_or_few_packets_is_insufficient():
    assert classify(obs()).label == "insuficiente"


def test_unknown_manufacturer_never_audio():
    from helpers import mfr

    c = classify(*[obs(mfr(0x012D, b"\x01\x02\x03"), t=i) for i in range(5)])
    assert c.label == "desconocido"


def test_invalid_rule_rejected():
    with pytest.raises(ValueError):
        parse_rules({"rules": [{"id": "X", "detector": "nope", "level": "estandar", "claim": {}}]})
