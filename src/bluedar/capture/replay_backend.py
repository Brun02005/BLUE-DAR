"""Reproduce una captura JSONL como si fuera un escaneo en vivo."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from ..store.jsonl_log import read_jsonl
from .base import Observation


class ReplayBackend:
    """`speed` = 1.0 respeta los tiempos originales; 0 reproduce sin esperas.

    Las observaciones grabadas ya están pseudonimizadas y redactadas, así que
    el pipeline no debe volver a aplicarles la capa de privacidad.
    """

    name = "replay"
    already_private = True

    def __init__(self, path: Path, speed: float = 1.0) -> None:
        self.path = path
        self.speed = speed
        self.dropped = 0

    async def observations(self) -> AsyncIterator[Observation]:
        loop = asyncio.get_running_loop()
        start_wall = loop.time()
        first_t = None
        for i, obs in enumerate(read_jsonl(self.path)):
            if self.speed <= 0:
                if i % 500 == 0:
                    await asyncio.sleep(0)  # ceder el loop para no bloquear el servidor web
            else:
                if first_t is None:
                    first_t = obs.t
                due = start_wall + (obs.t - first_t).total_seconds() / self.speed
                delay = due - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
            yield obs
