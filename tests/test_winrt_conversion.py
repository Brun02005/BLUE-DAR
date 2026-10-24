"""Conversión de event args de WinRT con objetos simulados (sin hardware)."""

from datetime import UTC, datetime
from types import SimpleNamespace

from bluedar.capture.bleak_backend import BleakBackend, observation_from_winrt


class Buf(bytes):
    pass


def section(t, data):
    return SimpleNamespace(data_type=t, data=Buf(data))


def args(adv_type=0, addr=0x4A1122334455, addr_type=1, rssi=-60, sections=()):
    return SimpleNamespace(
        bluetooth_address=addr,
        bluetooth_address_type=addr_type,
        raw_signal_strength_in_dbm=rssi,
        advertisement_type=adv_type,
        timestamp=datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
        is_connectable=adv_type == 0,
        is_scannable=adv_type in (0, 2),
        is_directed=False,
        transmit_power_level_in_dbm=None,
        advertisement=SimpleNamespace(data_sections=list(sections)),
    )


def test_observation_from_winrt():
    o = observation_from_winrt(args(sections=[section(0xFF, bytes.fromhex("4c001005"))]))
    assert o.address == "4A:11:22:33:44:55" and o.address_kind == "rpa"
    assert o.pdu == "adv_ind" and o.ad[0].type == 0xFF and o.connectable


def test_backend_picks_the_packet_that_just_arrived(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    backend = BleakBackend()
    device = SimpleNamespace(address="4A:11:22:33:44:55")
    adv = args(adv_type=0, rssi=-60)
    scan = args(adv_type=4, rssi=-61, sections=[section(0x09, b"x")])
    adv2 = args(adv_type=0, rssi=-62)

    def call(adv_obj, scan_obj):
        pair = SimpleNamespace(adv=adv_obj, scan=scan_obj)
        return backend._convert(device, SimpleNamespace(platform_data=(None, pair)))

    assert call(adv, None).rssi == -60
    assert call(adv, scan).pdu == "scan_rsp"
    assert call(adv2, scan).rssi == -62  # el scan_rsp viejo no se repite
