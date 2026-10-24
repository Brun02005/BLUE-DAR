"""Backend BLE basado en Bleak.

En Windows se lee cada paquete crudo desde `platform_data` (los event args de
WinRT), así se conservan el tipo de PDU, el tipo de dirección y las
estructuras AD exactamente como llegaron, sin la fusión adv+scan_rsp que hace
Bleak. En otras plataformas se reconstruyen las estructuras AD a partir de los
campos que expone Bleak (con pérdida: se marcan con extra["synthesized"]).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .base import AdStructure, Observation, classify_random_address, format_bdaddr

log = logging.getLogger(__name__)

_WIN_PDU = {
    0: "adv_ind",
    1: "adv_direct_ind",
    2: "adv_scan_ind",
    3: "adv_nonconn_ind",
    4: "scan_rsp",
    5: "extended",
}


def _to_utc(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    return datetime.now(UTC)


def observation_from_winrt(args: Any) -> Observation:
    """Convierte un BluetoothLEAdvertisementReceivedEventArgs en Observation."""
    address = format_bdaddr(int(args.bluetooth_address))
    try:
        address_type = int(args.bluetooth_address_type)
    except AttributeError:
        address_type = 2
    if address_type == 0:
        kind = "public"
    elif address_type == 1:
        kind = classify_random_address(address)
    else:
        kind = "unknown"

    sections = tuple(
        AdStructure.of(int(s.data_type), bytes(s.data)) for s in args.advertisement.data_sections
    )

    def opt(name: str) -> Any:
        try:
            return getattr(args, name)
        except AttributeError:
            return None

    return Observation(
        t=_to_utc(opt("timestamp")),
        transport="le",
        address=address,
        address_kind=kind,
        rssi=int(args.raw_signal_strength_in_dbm),
        backend="bleak-winrt",
        pdu=_WIN_PDU.get(int(args.advertisement_type)),
        connectable=opt("is_connectable"),
        scannable=opt("is_scannable"),
        directed=opt("is_directed"),
        tx_power=opt("transmit_power_level_in_dbm"),
        ad=sections,
    )


def _uuid16(u: str) -> int | None:
    try:
        parsed = uuid.UUID(u)
    except ValueError:
        return None
    if str(parsed).endswith("-0000-1000-8000-00805f9b34fb"):
        return int(str(parsed)[4:8], 16)
    return None


def observation_from_bleak(device: BLEDevice, adv: AdvertisementData) -> Observation:
    """Respaldo multiplataforma: reconstruye estructuras AD desde los campos de Bleak."""
    ad: list[AdStructure] = []
    if adv.local_name:
        ad.append(AdStructure.of(0x09, adv.local_name.encode()))
    if adv.tx_power is not None:
        ad.append(AdStructure.of(0x0A, int(adv.tx_power).to_bytes(1, "little", signed=True)))
    u16 = [v for v in (_uuid16(u) for u in adv.service_uuids) if v is not None]
    if u16:
        ad.append(AdStructure.of(0x03, b"".join(v.to_bytes(2, "little") for v in u16)))
    for u in adv.service_uuids:
        if _uuid16(u) is None:
            ad.append(AdStructure.of(0x07, uuid.UUID(u).bytes[::-1]))
    for u, data in adv.service_data.items():
        v = _uuid16(u)
        if v is not None:
            ad.append(AdStructure.of(0x16, v.to_bytes(2, "little") + data))
        else:
            ad.append(AdStructure.of(0x21, uuid.UUID(u).bytes[::-1] + data))
    for cid, data in adv.manufacturer_data.items():
        ad.append(AdStructure.of(0xFF, cid.to_bytes(2, "little") + data))

    return Observation(
        t=datetime.now(UTC),
        transport="le",
        address=device.address,
        address_kind="unknown",
        rssi=adv.rssi,
        backend="bleak",
        tx_power=adv.tx_power,
        ad=tuple(ad),
        extra={"synthesized": True},
    )


class BleakBackend:
    """Escaneo BLE continuo. Las observaciones se encolan con límite: si el
    consumidor se atrasa se descartan paquetes y se cuentan en `dropped`, en
    vez de crecer en memoria sin control."""

    name = "bleak"

    def __init__(self, scanning_mode: str = "active", queue_size: int = 10_000) -> None:
        self.scanning_mode = scanning_mode
        self.queue: asyncio.Queue[Observation] = asyncio.Queue(maxsize=queue_size)
        self.dropped = 0
        # Último par (adv, scan_rsp) visto por dirección, para saber cuál de
        # los dos es el paquete nuevo en cada callback de Bleak en Windows.
        self._last_pair: dict[str, tuple[Any, Any]] = {}

    def _on_detect(self, device: BLEDevice, adv: AdvertisementData) -> None:
        try:
            obs = self._convert(device, adv)
        except Exception:  # un paquete malformado no debe tirar el escaneo
            log.exception("No se pudo convertir un anuncio")
            return
        try:
            self.queue.put_nowait(obs)
        except asyncio.QueueFull:
            self.dropped += 1

    def _convert(self, device: BLEDevice, adv: AdvertisementData) -> Observation:
        if sys.platform == "win32" and isinstance(adv.platform_data, tuple) and len(adv.platform_data) == 2:
            pair = adv.platform_data[1]
            prev = self._last_pair.get(device.address)
            if pair.scan is not None and (prev is None or pair.scan is not prev[1]):
                current = pair.scan
            else:
                current = pair.adv
            self._last_pair[device.address] = (pair.adv, pair.scan)
            return observation_from_winrt(current)
        return observation_from_bleak(device, adv)

    async def observations(self) -> AsyncIterator[Observation]:
        scanner = BleakScanner(detection_callback=self._on_detect, scanning_mode=self.scanning_mode)
        await scanner.start()
        try:
            while True:
                yield await self.queue.get()
        finally:
            await scanner.stop()
