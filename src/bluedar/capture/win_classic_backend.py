"""Backend Bluetooth Classic para Windows (búsqueda / inquiry vía WinRT).

Solo ve equipos en modo descubrible (emparejamiento). Usa el mismo selector que
la pantalla "Agregar dispositivo" de Windows, que fuerza inquiry
(`System.Devices.Aep.Bluetooth.IssueInquiry`). Por cada equipo nuevo se lee el
Class of Device; las actualizaciones posteriores solo traen RSSI.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from .base import Observation, format_bdaddr

log = logging.getLogger(__name__)

_SIGNAL = "System.Devices.Aep.SignalStrength"
_PROPS = [_SIGNAL, "System.Devices.Aep.IsPresent"]


def _unbox_int(value: Any) -> int | None:
    if value is None:
        return None
    import winrt.system as ws

    for fn in (ws.unbox_int32, ws.unbox_int16, ws.unbox_int8, ws.unbox_uint8):
        try:
            return int(fn(value))
        except Exception:
            continue
    return None


class WinClassicBackend:
    name = "winrt-classic"

    def __init__(self, queue_size: int = 2_000) -> None:
        self.queue: asyncio.Queue[Observation] = asyncio.Queue(maxsize=queue_size)
        self.dropped = 0
        # id de WinRT → (dirección, CoD, nombre). Solo en memoria.
        self._known: dict[str, tuple[str, int | None, str | None]] = {}

    def _emit(self, obs: Observation) -> None:
        try:
            self.queue.put_nowait(obs)
        except asyncio.QueueFull:
            self.dropped += 1

    async def _resolve(self, dev_id: str, name: str | None, rssi: int | None) -> None:
        from winrt.windows.devices.bluetooth import BluetoothDevice

        try:
            device = await BluetoothDevice.from_id_async(dev_id)
        except Exception:
            log.debug("from_id_async falló para un dispositivo Classic", exc_info=True)
            return
        if device is None:
            return
        address = format_bdaddr(int(device.bluetooth_address))
        cod = int(device.class_of_device.raw_value)
        self._known[dev_id] = (address, cod, name)
        self._emit(self._observation(address, cod, name, rssi))

    @staticmethod
    def _observation(address: str, cod: int | None, name: str | None, rssi: int | None) -> Observation:
        return Observation(
            t=datetime.now(UTC),
            transport="bredr",
            address=address,
            address_kind="public",
            rssi=rssi,
            backend="winrt-classic",
            pdu="inquiry",
            cod=cod,
            name=name or None,
        )

    async def observations(self) -> AsyncIterator[Observation]:
        from winrt.windows.devices.bluetooth import BluetoothDevice
        from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind

        loop = asyncio.get_running_loop()
        tasks: set[asyncio.Task] = set()

        def spawn(coro: Any) -> None:
            task = loop.create_task(coro)
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        def on_added(_sender: Any, info: Any) -> None:
            rssi = _unbox_int(info.properties.get(_SIGNAL))
            name = info.name
            loop.call_soon_threadsafe(spawn, self._resolve(info.id, name, rssi))

        def on_updated(_sender: Any, update: Any) -> None:
            rssi = _unbox_int(update.properties.get(_SIGNAL))
            dev_id = update.id

            def handle() -> None:
                known = self._known.get(dev_id)
                if known is not None and rssi is not None:
                    self._emit(self._observation(known[0], known[1], known[2], rssi))

            loop.call_soon_threadsafe(handle)

        selector = BluetoothDevice.get_device_selector_from_pairing_state(False)
        watcher = DeviceInformation.create_watcher(
            selector, _PROPS, DeviceInformationKind.ASSOCIATION_ENDPOINT
        )
        added_token = watcher.add_added(on_added)
        updated_token = watcher.add_updated(on_updated)
        watcher.start()
        try:
            while True:
                yield await self.queue.get()
        finally:
            watcher.remove_added(added_token)
            watcher.remove_updated(updated_token)
            watcher.stop()
            for task in tasks:
                task.cancel()
