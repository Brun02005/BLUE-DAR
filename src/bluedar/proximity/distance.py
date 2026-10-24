"""Distancia estimada a partir del RSSI, SIEMPRE como intervalo.

Nunca un número solo: el RSSI → metros depende de la potencia del emisor (por
eso hay que calibrar por dispositivo) y del exponente de pérdida, que cambia con
las paredes. A pocos metros en línea de vista el intervalo es acotado; a través
de varias paredes (ej. casas vecinas) se vuelve muy ancho, y eso es honesto: la
atenuación de las paredes, no la distancia, es la que manda.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Modelo genérico (sin calibrar). Un BLE típico ronda -59 dBm a 1 m, pero varía
# mucho por dispositivo: por eso, sin calibración, el intervalo se ensancha.
GENERIC_REF_DBM = -59.0
N_NOMINAL = 2.5
N_LOW = 2.0   # casi espacio libre: da la distancia MÁS grande
N_HIGH = 4.0  # muchos obstáculos: da la distancia MÁS chica
SIGMA_FLOOR_DB = 6.0
UNCERTAIN_ABOVE_M = 40.0
MIN_M = 0.2


@dataclass(frozen=True, slots=True)
class DistanceEstimate:
    low_m: float
    high_m: float
    nominal_m: float
    calibrated: bool
    uncertain: bool  # la cota superior se fue a una escala donde el número ya no es confiable

    def text(self) -> str:
        suffix = "" if self.calibrated else " (sin calibrar)"
        if self.high_m < 1.0:
            return f"muy cerca (< 1 m){suffix}"
        if self.uncertain:
            return f"> {_fmt(self.low_m)} m (señal muy débil, muy incierto){suffix}"
        return f"≈ {_fmt(self.low_m)}–{_fmt(self.high_m)} m{suffix}"


def _fmt(m: float) -> str:
    return f"{m:.1f}" if m < 10 else str(round(m))


def _dist(rssi: float, ref: float, n: float) -> float:
    return max(MIN_M, 10 ** ((ref - rssi) / (10 * n)))


def estimate_distance(
    rssi: float,
    spread_db: float | None = None,
    ref_dbm: float = GENERIC_REF_DBM,
    n: float = N_NOMINAL,
    calibrated: bool = False,
) -> DistanceEstimate:
    sigma = max(SIGMA_FLOOR_DB, (spread_db or 0.0) / 1.35)  # IQR → σ
    # Más señal (rssi alto) y más obstáculos (n alto) → distancia menor, y al revés.
    low = _dist(rssi + sigma, ref_dbm, N_HIGH if not calibrated else max(n, N_NOMINAL))
    high = _dist(rssi - sigma, ref_dbm, N_LOW if not calibrated else min(n, N_NOMINAL))
    nominal = _dist(rssi, ref_dbm, n)
    return DistanceEstimate(
        low_m=round(low, 2),
        high_m=round(high, 2),
        nominal_m=round(nominal, 2),
        calibrated=calibrated,
        uncertain=high > UNCERTAIN_ABOVE_M,
    )
