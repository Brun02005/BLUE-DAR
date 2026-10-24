"""Capa de privacidad: se aplica a cada observación en vivo antes de que salga
del backend hacia cualquier otro módulo (memoria compartida, disco, UI).

- La dirección se reemplaza por HMAC(clave de sesión, dirección). La clave
  solo existe en memoria durante la sesión: entre sesiones no hay forma de
  correlacionar el mismo dispositivo.
- Los nombres (AD 0x08/0x09 y el nombre Classic) se reducen a una categoría
  heurística ("auricular:buds") y se descartan, salvo `keep_names` (sesiones de
  laboratorio con dispositivos propios).
- La dirección BR/EDR que Swift Pair incluye en claro se pone en cero.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import replace

from ..capture.base import AdStructure, Observation
from ..decode.ad_structures import AD_MANUFACTURER, AD_NAME, CID_MICROSOFT
from ..decode.swift_pair import BEACON_ID, BREDR_ADDR_SLICE

NameHinter = Callable[[str], str | None]


class Privacy:
    def __init__(
        self,
        keep_names: bool = False,
        name_hinter: NameHinter | None = None,
        key: bytes | None = None,
    ) -> None:
        self._key = key or secrets.token_bytes(32)
        self.keep_names = keep_names
        self.name_hinter = name_hinter or (lambda _name: None)

    @property
    def key_hex(self) -> str:
        """Para compartir con nodos receptores de la misma sesión (red local)."""
        return self._key.hex()

    def pseudonym(self, address: str) -> str:
        return hmac.new(self._key, address.upper().encode(), hashlib.sha256).hexdigest()[:12]

    def apply(self, obs: Observation) -> Observation:
        names: list[str] = []
        ad: list[AdStructure] = []
        for s in obs.ad:
            if s.type in AD_NAME and s.data is not None:
                names.append(s.data.decode("utf-8", errors="replace"))
                ad.append(s if self.keep_names else AdStructure(s.type, None, s.length))
            elif s.type == AD_MANUFACTURER and s.data is not None and _is_swift_pair_bredr(s.data):
                data = bytearray(s.data)
                start, stop = 2 + BREDR_ADDR_SLICE.start, 2 + BREDR_ADDR_SLICE.stop
                data[start:stop] = bytes(stop - start)
                ad.append(AdStructure.of(s.type, bytes(data)))
            else:
                ad.append(s)
        if obs.name:
            names.append(obs.name)

        hint = next((h for h in map(self.name_hinter, names) if h), None)
        return replace(
            obs,
            address=self.pseudonym(obs.address),
            ad=tuple(ad),
            name=obs.name if self.keep_names else None,
            name_hint=hint,
            has_name=bool(names) or obs.has_name,
        )


def _is_swift_pair_bredr(data: bytes) -> bool:
    return (
        len(data) >= 2 + BREDR_ADDR_SLICE.stop
        and int.from_bytes(data[:2], "little") == CID_MICROSOFT
        and data[2] == BEACON_ID
        and data[3] == 0x01
    )
