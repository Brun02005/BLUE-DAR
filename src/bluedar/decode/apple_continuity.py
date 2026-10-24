"""Mensajes Apple Continuity (manufacturer data, Company ID 0x004C).

Formato documentado por ingeniería inversa (furiousMAC/continuity; Celosia &
Cunche, PoPETs 2020), no por Apple. Solo se leen el tipo de mensaje; en
Proximity Pairing, el modelo declarado; y en Find My, la pista de tipo y si el
payload es el de "separado del dueño". No se decodifican batería, contadores,
claves ni payloads cifrados: no hacen falta para clasificar y facilitan el rastreo.

Find My (0x12) según AirGuard (seemoo-lab, TU Darmstadt), filtros de escaneo
de AirTag.kt / AirPods.kt / AppleFindMy.kt:
- longitud 0x19 (25 bytes, clave pública completa) = separado del dueño;
  longitud corta = cerca del dueño / conectado recientemente.
- status byte (primer byte del valor) & 0x18: 0x10 → AirTag, 0x18 → AirPods.
  Solo en el payload de separado, donde AirGuard lo define. Otros valores no se
  mapean. [VERIFICAR] con dispositivos propios (H4).
La clave rota (~15 min): la pista dice "de qué tipo", nunca "cuál".
"""

from __future__ import annotations

from dataclasses import dataclass

TYPE_NAMES = {
    0x05: "AirDrop",
    0x07: "Proximity Pairing",
    0x09: "AirPlay Target",
    0x0C: "Handoff",
    0x0F: "Nearby Action",
    0x10: "Nearby Info",
    0x12: "Find My (Offline Finding)",
}

PROXIMITY_PAIRING = 0x07
FIND_MY = 0x12
FIND_MY_SEPARATED_LENGTH = 0x19
FIND_MY_TYPE_MASK = 0x18
FIND_MY_TYPE_HINTS = {0x10: "AirTag", 0x18: "AirPods"}


@dataclass(frozen=True, slots=True)
class ContinuityMessage:
    type: int
    length: int
    # Proximity Pairing: los 2 bytes de modelo en el orden en que vienen en el paquete.
    model: str | None = None
    # Find My: pista de tipo ("AirPods", "AirTag" o None) y si es el payload de "separado".
    find_my_hint: str | None = None
    separated: bool | None = None

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type, f"tipo 0x{self.type:02X}")


def parse_continuity(payload: bytes) -> tuple[list[ContinuityMessage], list[str]]:
    """Recorre el TLV (tipo, longitud, valor). Devuelve mensajes y errores de formato."""
    messages: list[ContinuityMessage] = []
    errors: list[str] = []
    i = 0
    while i + 2 <= len(payload):
        mtype, mlen = payload[i], payload[i + 1]
        value = payload[i + 2 : i + 2 + mlen]
        if len(value) < mlen:
            errors.append(f"Continuity 0x{mtype:02X}: longitud {mlen} excede el paquete")
            break
        model = hint = separated = None
        if mtype == PROXIMITY_PAIRING and mlen >= 3:
            # value[0] es el prefijo (0x01 observado); value[1:3] el modelo.
            model = value[1:3].hex()
        elif mtype == FIND_MY:
            separated = mlen == FIND_MY_SEPARATED_LENGTH
            # AirGuard define la pista sobre el payload largo; en el corto no se extrapola.
            if separated:
                hint = FIND_MY_TYPE_HINTS.get(value[0] & FIND_MY_TYPE_MASK)
        messages.append(ContinuityMessage(mtype, mlen, model, hint, separated))
        i += 2 + mlen
    return messages, errors
