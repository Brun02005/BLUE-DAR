"""Constructores de paquetes sintéticos según los formatos documentados.

No reemplazan a las capturas reales: cuando existan capturas de dispositivos
propios, agregar sus fixtures en tests/fixtures/ (ya pseudonimizadas).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bluedar.capture.base import AdStructure, Observation

T0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)


def mfr(cid: int, payload: bytes) -> AdStructure:
    return AdStructure.of(0xFF, cid.to_bytes(2, "little") + payload)


def proximity_pairing(model: bytes = bytes.fromhex("0e20")) -> AdStructure:
    value = b"\x01" + model + bytes.fromhex("55aab5310000") + bytes(16)
    assert len(value) == 25
    return mfr(0x004C, bytes([0x07, len(value)]) + value)


def nearby_info() -> AdStructure:
    return mfr(0x004C, bytes.fromhex("1005031c1a2b3c"))


def find_my(status: int = 0x00, separated: bool = True) -> AdStructure:
    length = 0x19 if separated else 0x02
    return mfr(0x004C, bytes([0x12, length, status]) + bytes(length - 1))


def fast_pair(service_payload: bytes) -> AdStructure:
    return AdStructure.of(0x16, (0xFE2C).to_bytes(2, "little") + service_payload)


def appearance(value: int) -> AdStructure:
    return AdStructure.of(0x19, value.to_bytes(2, "little"))


def name(text: str) -> AdStructure:
    return AdStructure.of(0x09, text.encode())


def obs(*ad: AdStructure, address: str = "4A:11:22:33:44:55", rssi: int = -60, t: float = 0.0, **kw) -> Observation:
    return Observation(
        t=T0 + timedelta(seconds=t),
        transport=kw.pop("transport", "le"),
        address=address,
        address_kind=kw.pop("address_kind", "rpa"),
        rssi=rssi,
        backend="test",
        pdu=kw.pop("pdu", "adv_ind"),
        ad=tuple(ad),
        **kw,
    )
