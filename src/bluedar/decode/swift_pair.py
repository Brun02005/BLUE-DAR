"""Microsoft Swift Pair (manufacturer data, Company ID 0x0006).

Microsoft Learn, "Swift Pair": beacon + subescenario + byte RSSI reservado
(0x80). Subescenarios: 0x00 solo LE; 0x01 BR/EDR descubierto vía LE
(dirección BR/EDR + CoD); 0x02 LE + BR/EDR con Secure Connections (CoD).
El valor del beacon ID (0x03) y la posición exacta de los campos salen de las
figuras de esa página y quedan [VERIFICAR] contra un dispositivo real.
"""

from __future__ import annotations

from dataclasses import dataclass

BEACON_ID = 0x03
RESERVED_RSSI = 0x80
SCENARIOS = {0x00: "solo LE", 0x01: "BR/EDR vía LE", 0x02: "LE + BR/EDR (SC)"}

# Desplazamiento de la dirección BR/EDR dentro del payload (después del CID),
# usado también por la capa de privacidad para redactarla.
BREDR_ADDR_SLICE = slice(3, 9)


@dataclass(frozen=True, slots=True)
class SwiftPairInfo:
    scenario: int
    cod: int | None

    @property
    def scenario_name(self) -> str:
        return SCENARIOS.get(self.scenario, f"0x{self.scenario:02X}")


def parse_swift_pair(payload: bytes) -> SwiftPairInfo | None:
    """`payload` es el manufacturer data sin el Company ID."""
    if len(payload) < 3 or payload[0] != BEACON_ID or payload[2] != RESERVED_RSSI:
        return None
    scenario = payload[1]
    cod = None
    if scenario == 0x01 and len(payload) >= 12:
        cod = int.from_bytes(payload[9:12], "little")
    elif scenario == 0x02 and len(payload) >= 6:
        cod = int.from_bytes(payload[3:6], "little")
    return SwiftPairInfo(scenario, cod)
