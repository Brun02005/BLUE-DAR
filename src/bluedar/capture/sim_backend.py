"""Backend simulado para el modo demo: varios receptores y dispositivos ficticios
con posición verdadera conocida. Sirve para ver el plano funcionando y comparar
la estimación contra la verdad sin hardware.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from ..positioning.room import Room
from .base import AdStructure, Observation

# Pseudónimos fijos (hex, como los reales) para poder pre-asignar LAB-IDs.
SIM_DEVICES = {
    "5151a0000001": ("LAB-SIM-AURIC", "auricular"),
    "5151a0000002": ("LAB-SIM-PARL", "parlante"),
}
_AIRPODS_AD = AdStructure.of(
    0xFF, bytes.fromhex("4c00") + bytes([0x07, 25]) + bytes.fromhex("010e2055aab5310000") + bytes(16)
)
_SPEAKER_AD = AdStructure.of(0x19, (0x0841).to_bytes(2, "little"))


class SimBackend:
    name = "simulador"
    already_private = True

    def __init__(self, room: Room, sigma_db: float = 5.0, rate_hz: float = 2.0, seed: int = 3) -> None:
        self.room = room
        self.sigma_db = sigma_db
        self.rate_hz = rate_hz
        self.rng = random.Random(seed)
        self.dropped = 0
        self.truth: dict[str, tuple[float, float]] = {}

    def _positions(self, t: float) -> dict[str, tuple[float, float]]:
        w, h = self.room.width, self.room.height
        moving = (w / 2 + 0.35 * w * math.cos(t / 12), h / 2 + 0.35 * h * math.sin(t / 12))
        return {"5151a0000001": moving, "5151a0000002": (0.8 * w, 0.25 * h)}

    async def observations(self) -> AsyncIterator[Observation]:
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            await asyncio.sleep(1.0 / self.rate_hz)
            t = loop.time() - start
            now = datetime.now(UTC)
            self.truth = self._positions(t)
            for dev_id, (x, y) in self.truth.items():
                ad = _AIRPODS_AD if SIM_DEVICES[dev_id][1] == "auricular" else _SPEAKER_AD
                for node in self.room.nodes.values():
                    d = max(0.3, math.hypot(x - node.x, y - node.y))
                    rssi = node.ref_dbm - 10 * node.n * math.log10(d) + self.rng.gauss(0, self.sigma_db)
                    yield Observation(
                        t=now, transport="le", address=dev_id, address_kind="rpa",
                        rssi=round(rssi), backend="simulador", pdu="adv_ind", ad=(ad,), node=node.id,
                    )
