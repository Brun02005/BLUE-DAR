from helpers import mfr, name, obs

from bluedar.classify.rules_engine import load_default_ruleset
from bluedar.privacy.pseudonym import Privacy


def test_pseudonym_stable_within_session_and_different_across():
    a, b = Privacy(), Privacy()
    addr = "4A:11:22:33:44:55"
    assert a.pseudonym(addr) == a.pseudonym(addr.lower())
    assert a.pseudonym(addr) != b.pseudonym(addr)
    assert addr.replace(":", "").lower() not in a.pseudonym(addr)


def test_names_are_redacted_but_hinted():
    rs = load_default_ruleset()
    p = Privacy(name_hinter=rs.name_hint)
    out = p.apply(obs(name("Galaxy Buds2 de Juan")))
    assert out.ad[0].data is None and out.ad[0].length == len("Galaxy Buds2 de Juan".encode())
    assert out.has_name and out.name_hint == "auricular:buds"
    assert out.address != "4A:11:22:33:44:55"


def test_keep_names_for_lab_sessions():
    p = Privacy(keep_names=True)
    out = p.apply(obs(name("MiParlante")))
    assert out.ad[0].data == b"MiParlante"


def test_classic_name_dropped():
    p = Privacy()
    out = p.apply(obs(transport="bredr", name="Speaker de Ana", pdu="inquiry"))
    assert out.name is None and out.has_name


def test_swift_pair_bredr_address_zeroed():
    payload = bytes([0x03, 0x01, 0x80]) + bytes.fromhex("aabbccddeeff") + (0x240404).to_bytes(3, "little")
    out = Privacy().apply(obs(mfr(0x0006, payload)))
    data = out.ad[0].data
    assert data[5:11] == bytes(6)
    assert data[11:14] == (0x240404).to_bytes(3, "little")
