"""Diagnóstico del adaptador Bluetooth (qué puede capturar esta máquina)."""

from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Any


def _pkg_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


async def adapter_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "bleak": _pkg_version("bleak"),
    }
    if sys.platform != "win32":
        info["note"] = "Diagnóstico detallado implementado solo para Windows."
        return info

    from winrt.windows.devices.bluetooth import BluetoothAdapter

    adapter = await BluetoothAdapter.get_default_async()
    if adapter is None:
        info["error"] = "No hay adaptador Bluetooth"
        return info
    radio = await adapter.get_radio_async()
    info["radio_state"] = radio.state.name if radio else None
    for attr in (
        "is_low_energy_supported",
        "is_classic_supported",
        "is_central_role_supported",
        "is_advertisement_offload_supported",
        "is_extended_advertising_supported",
        "max_advertisement_data_length",
        "is_low_energy_coded_phy_supported",
        "is_low_energy_uncoded2_m_phy_supported",
    ):
        try:
            info[attr] = getattr(adapter, attr)
        except (AttributeError, OSError):
            info[attr] = None
    # La dirección propia del adaptador no se incluye: no hace falta para el diagnóstico.
    info["device_id_vendor"] = _vendor_from_device_id(adapter.device_id)
    return info


def _vendor_from_device_id(device_id: str) -> str | None:
    upper = device_id.upper()
    for token in ("VID_", "VID&"):
        if token in upper:
            start = upper.index(token)
            return device_id[start : start + 17]
    return None
