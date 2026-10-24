"""Decodificación de estructuras AD genéricas (Bluetooth SIG, Assigned Numbers)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..capture.base import Observation
from .apple_continuity import ContinuityMessage, parse_continuity
from .fast_pair import FastPairInfo, parse_fast_pair
from .swift_pair import SwiftPairInfo, parse_swift_pair

AD_FLAGS = 0x01
AD_UUID16 = (0x02, 0x03)
AD_UUID32 = (0x04, 0x05)
AD_UUID128 = (0x06, 0x07)
AD_NAME = (0x08, 0x09)
AD_TX_POWER = 0x0A
AD_COD = 0x0D
AD_SERVICE_DATA16 = 0x16
AD_APPEARANCE = 0x19
AD_MANUFACTURER = 0xFF

CID_APPLE = 0x004C
CID_MICROSOFT = 0x0006
UUID_FAST_PAIR = 0xFE2C


@dataclass(slots=True)
class Decoded:
    flags: int | None = None
    uuids16: set[int] = field(default_factory=set)
    uuids128: set[str] = field(default_factory=set)
    service_data16: dict[int, bytes] = field(default_factory=dict)
    manufacturer: dict[int, bytes] = field(default_factory=dict)
    appearance: int | None = None
    tx_power: int | None = None
    cod: int | None = None
    apple: list[ContinuityMessage] = field(default_factory=list)
    fast_pair: FastPairInfo | None = None
    swift_pair: SwiftPairInfo | None = None
    malformed: list[str] = field(default_factory=list)


def decode(obs: Observation) -> Decoded:
    d = Decoded(cod=obs.cod, tx_power=obs.tx_power)
    for s in obs.ad:
        data = s.data
        if data is None:
            continue
        t = s.type
        if t == AD_FLAGS and data:
            d.flags = data[0]
        elif t in AD_UUID16:
            d.uuids16.update(int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data) - 1, 2))
        elif t in AD_UUID128:
            for i in range(0, len(data) - 15, 16):
                d.uuids128.add(data[i : i + 16][::-1].hex())
        elif t == AD_TX_POWER and data:
            d.tx_power = int.from_bytes(data[:1], "little", signed=True)
        elif t == AD_COD and len(data) >= 3:
            d.cod = int.from_bytes(data[:3], "little")
        elif t == AD_SERVICE_DATA16 and len(data) >= 2:
            d.service_data16[int.from_bytes(data[:2], "little")] = data[2:]
        elif t == AD_APPEARANCE and len(data) >= 2:
            d.appearance = int.from_bytes(data[:2], "little")
        elif t == AD_MANUFACTURER:
            if len(data) < 2:
                d.malformed.append("manufacturer data < 2 bytes")
                continue
            d.manufacturer[int.from_bytes(data[:2], "little")] = data[2:]

    if CID_APPLE in d.manufacturer:
        d.apple, errors = parse_continuity(d.manufacturer[CID_APPLE])
        d.malformed.extend(errors)
    if UUID_FAST_PAIR in d.service_data16:
        d.fast_pair = parse_fast_pair(d.service_data16[UUID_FAST_PAIR])
    if CID_MICROSOFT in d.manufacturer:
        d.swift_pair = parse_swift_pair(d.manufacturer[CID_MICROSOFT])
    return d


def company_id_of(obs: Observation) -> list[int]:
    return [
        int.from_bytes(s.data[:2], "little")
        for s in obs.ad
        if s.type == AD_MANUFACTURER and s.data is not None and len(s.data) >= 2
    ]
