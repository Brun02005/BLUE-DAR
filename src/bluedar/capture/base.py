"""Tipos compartidos por todos los backends de captura."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

Transport = Literal["le", "bredr"]

# Tipos de PDU de anuncio. None si el backend no lo informa.
PDU_TYPES = (
    "adv_ind",
    "adv_direct_ind",
    "adv_scan_ind",
    "adv_nonconn_ind",
    "scan_rsp",
    "extended",
    "inquiry",
)


@dataclass(frozen=True, slots=True)
class AdStructure:
    """Una estructura AD (longitud, tipo, datos) tal como vino en el paquete.

    `data` es None cuando la capa de privacidad la redactó; `length` conserva
    la longitud original para poder analizar el paquete igual.
    """

    type: int
    data: bytes | None
    length: int

    @classmethod
    def of(cls, type_: int, data: bytes) -> AdStructure:
        return cls(type_, data, len(data))

    @property
    def redacted(self) -> bool:
        return self.data is None


@dataclass(slots=True)
class Observation:
    """Un paquete recibido (BLE) o una respuesta de búsqueda (Classic).

    Antes de pasar por `privacy.Privacy.apply`, `address` es la dirección real y
    solo vive en memoria. Después es un pseudónimo de sesión.
    """

    t: datetime
    transport: Transport
    address: str
    address_kind: str  # public | random_static | rpa | nrpa | random | unknown
    rssi: int | None
    backend: str
    pdu: str | None = None
    connectable: bool | None = None
    scannable: bool | None = None
    directed: bool | None = None
    tx_power: int | None = None
    ad: tuple[AdStructure, ...] = ()
    cod: int | None = None
    # Nombre fuera de las estructuras AD (Classic). Se redacta como los nombres AD.
    name: str | None = None
    # Categoría heurística derivada del nombre antes de redactarlo (p. ej. "auricular:buds").
    name_hint: str | None = None
    # True si el paquete traía un nombre (aunque esté redactado).
    has_name: bool = False
    # Receptor que escuchó el paquete ("local" = el escáner de esta máquina).
    node: str = "local"
    extra: dict = field(default_factory=dict)


class Backend(Protocol):
    name: str

    def observations(self) -> AsyncIterator[Observation]:
        """Emite observaciones hasta que se cancela la tarea que la consume."""
        ...


def classify_random_address(address: str) -> str:
    """Subtipo de una dirección aleatoria BLE según sus 2 bits más altos (Core Spec, Vol 6, Part B, 1.3)."""
    try:
        top = int(address.split(":")[0], 16) >> 6
    except ValueError:
        return "random"
    return {0b11: "random_static", 0b01: "rpa", 0b00: "nrpa"}.get(top, "random")


def format_bdaddr(value: int) -> str:
    return ":".join(f"{(value >> (8 * i)) & 0xFF:02X}" for i in reversed(range(6)))
