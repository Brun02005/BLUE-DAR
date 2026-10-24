"""Google Fast Pair (service data 0xFE2C).

developers.google.com/nearby/fast-pair/specifications/service/provider:
en modo emparejamiento el service data es el Model ID de 24 bits; fuera de ese
modo es Account Data (filtro de claves + salt) y no incluye Model ID.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FastPairInfo:
    discoverable: bool
    model_id: str | None  # hex de 6 dígitos, solo en modo emparejamiento


def parse_fast_pair(data: bytes) -> FastPairInfo:
    if len(data) == 3:
        return FastPairInfo(discoverable=True, model_id=data.hex())
    return FastPairInfo(discoverable=False, model_id=None)
