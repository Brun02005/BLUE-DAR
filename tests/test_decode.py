from helpers import appearance, fast_pair, find_my, mfr, nearby_info, obs, proximity_pairing

from bluedar.capture.base import AdStructure, classify_random_address, format_bdaddr
from bluedar.decode.ad_structures import decode
from bluedar.decode.apple_continuity import parse_continuity
from bluedar.decode.class_of_device import describe_appearance, describe_cod
from bluedar.decode.swift_pair import parse_swift_pair


def test_proximity_pairing_model_in_packet_order():
    d = decode(obs(proximity_pairing()))
    assert [m.type for m in d.apple] == [0x07]
    assert d.apple[0].model == "0e20"


def test_continuity_multiple_tlvs_and_truncation():
    msgs, errors = parse_continuity(bytes.fromhex("1005031c1a2b3c") + bytes.fromhex("0c0e00"))
    assert [m.type for m in msgs] == [0x10]
    assert errors and "excede" in errors[0]


def test_nearby_info_and_find_my():
    assert decode(obs(nearby_info())).apple[0].type == 0x10
    assert decode(obs(find_my())).apple[0].type == 0x12


def test_find_my_type_hint_and_state():
    airpods = decode(obs(find_my(status=0x18))).apple[0]
    assert airpods.find_my_hint == "AirPods" and airpods.separated
    airtag = decode(obs(find_my(status=0x10 | 0x40))).apple[0]  # bits de batería no afectan la pista
    assert airtag.find_my_hint == "AirTag"
    unknown = decode(obs(find_my(status=0x08))).apple[0]
    assert unknown.find_my_hint is None
    nearby = decode(obs(find_my(status=0x18, separated=False))).apple[0]
    assert nearby.separated is False and nearby.find_my_hint is None  # no se extrapola al payload corto


def test_fast_pair_model_vs_account_data():
    with_model = decode(obs(fast_pair(bytes.fromhex("a1b2c3")))).fast_pair
    assert with_model.discoverable and with_model.model_id == "a1b2c3"
    account = decode(obs(fast_pair(bytes.fromhex("00" + "11" * 9 + "2233")))).fast_pair
    assert not account.discoverable and account.model_id is None


def test_swift_pair_scenarios():
    cod = (0x240404).to_bytes(3, "little")
    sp = parse_swift_pair(bytes([0x03, 0x02, 0x80]) + cod + b"Name")
    assert sp.scenario == 0x02 and sp.cod == 0x240404
    sp = parse_swift_pair(bytes([0x03, 0x01, 0x80]) + bytes(6) + cod)
    assert sp.cod == 0x240404
    assert parse_swift_pair(bytes([0x01, 0x09, 0x20])) is None  # Microsoft CDP, no es Swift Pair


def test_appearance_and_cod_types():
    assert describe_appearance(0x0941)[1] == "auricular"
    assert describe_appearance(0x0841)[1] == "parlante"
    assert describe_appearance(0x00C0)[1] is None
    assert describe_cod(0x240404)[1] == "auricular"  # Audio/Video · Wearable Headset
    assert describe_cod(0x240414)[1] == "parlante"  # Audio/Video · Loudspeaker
    assert describe_cod(0x3C0420)[1] is None  # Car audio: no se tipa
    assert describe_cod(0x5A020C)[1] is None  # teléfono


def test_generic_ad_fields():
    d = decode(obs(appearance(0x0941), AdStructure.of(0x0A, b"\xf4"), AdStructure.of(0x03, bytes.fromhex("5018"))))
    assert d.appearance == 0x0941 and d.tx_power == -12 and 0x1850 in d.uuids16


def test_redacted_and_malformed_sections_are_skipped():
    d = decode(obs(AdStructure(0x09, None, 7), AdStructure.of(0xFF, b"\x4c")))
    assert d.manufacturer == {} and d.malformed


def test_address_helpers():
    assert format_bdaddr(0xA1B2C3D4E5F6) == "A1:B2:C3:D4:E5:F6"
    assert classify_random_address("C1:00:00:00:00:00") == "random_static"
    assert classify_random_address("4A:00:00:00:00:00") == "rpa"
    assert classify_random_address("2A:00:00:00:00:00") == "nrpa"


def test_microsoft_cdp_is_not_swift_pair():
    d = decode(obs(mfr(0x0006, bytes.fromhex("0109202656f276"))))
    assert d.swift_pair is None
