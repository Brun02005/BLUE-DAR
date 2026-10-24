"""Estimación de posición por trilateración RSSI.

Modelo log-distancia por receptor: RSSI(d) = ref_dbm − 10·n·log10(d). Cada
receptor aporta un rango d_i con incertidumbre σ_i (crece con d: un error de
RSSI fijo en dB es un error multiplicativo en metros). La posición se obtiene
por mínimos cuadrados no lineales ponderados (Gauss-Newton amortiguado) y la
incertidumbre sale de la covarianza (JᵀWJ)⁻¹, escalada por los residuos.

Con < 3 receptores no hay solución única en 2D y no se devuelve posición.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_NODES = 3
RSSI_SIGMA_FLOOR_DB = 4.0  # sombreado típico en interiores; nunca se asume menos
MIN_RANGE_M = 0.2


@dataclass(frozen=True, slots=True)
class Range:
    node: str
    x: float
    y: float
    distance: float
    sigma: float  # metros


@dataclass(frozen=True, slots=True)
class Fix:
    x: float
    y: float
    radius: float  # incertidumbre aproximada (1σ radial), metros
    residual_rms: float
    ranges: tuple[Range, ...]


def rssi_to_distance(rssi: float, ref_dbm: float, n: float) -> float:
    return max(MIN_RANGE_M, 10 ** ((ref_dbm - rssi) / (10 * n)))


def distance_sigma(distance: float, n: float, rssi_sigma_db: float) -> float:
    """Propagación de σ_RSSI (dB) a σ_d (m): dd/dRSSI = d·ln(10)/(10·n)."""
    return max(0.1, distance * math.log(10) / (10 * n) * rssi_sigma_db)


def make_range(node: str, x: float, y: float, rssi: float, ref_dbm: float, n: float, rssi_sigma_db: float | None) -> Range:
    sigma_db = max(RSSI_SIGMA_FLOOR_DB, rssi_sigma_db or 0.0)
    d = rssi_to_distance(rssi, ref_dbm, n)
    return Range(node, x, y, d, distance_sigma(d, n, sigma_db))


def trilaterate(ranges: list[Range], width: float, height: float, iterations: int = 40) -> Fix | None:
    if len(ranges) < MIN_NODES:
        return None
    weights = [1.0 / (r.sigma**2) for r in ranges]

    # Punto inicial: centroide ponderado por cercanía.
    wsum = sum(1.0 / r.distance**2 for r in ranges)
    x = sum(r.x / r.distance**2 for r in ranges) / wsum
    y = sum(r.y / r.distance**2 for r in ranges) / wsum

    jtwj = (0.0, 0.0, 0.0)
    for _ in range(iterations):
        a = b = c = gx = gy = 0.0  # JᵀWJ = [[a, b], [b, c]], JᵀWe = [gx, gy]
        for r, w in zip(ranges, weights):
            dx, dy = x - r.x, y - r.y
            dist = math.hypot(dx, dy) or 1e-6
            ux, uy = dx / dist, dy / dist
            e = dist - r.distance
            a += w * ux * ux
            b += w * ux * uy
            c += w * uy * uy
            gx += w * ux * e
            gy += w * uy * e
        jtwj = (a, b, c)
        lam = 1e-3 * (a + c)
        det = (a + lam) * (c + lam) - b * b
        if det <= 1e-12:
            return None  # geometría degenerada (receptores alineados)
        step_x = -((c + lam) * gx - b * gy) / det
        step_y = -(-b * gx + (a + lam) * gy) / det
        x = min(max(x + step_x, 0.0), width)
        y = min(max(y + step_y, 0.0), height)
        if math.hypot(step_x, step_y) < 1e-4:
            break

    residuals = [math.hypot(x - r.x, y - r.y) - r.distance for r in ranges]
    chi2 = sum(w * e * e for w, e in zip(weights, residuals))
    dof = max(1, len(ranges) - 2)
    scale = max(1.0, chi2 / dof)
    a, b, c = jtwj
    det = a * c - b * b
    if det <= 1e-12:
        return None
    # Traza de la covarianza (JᵀWJ)⁻¹ · escala → radio 1σ.
    radius = math.sqrt(scale * (a + c) / det)
    rms = math.sqrt(sum(e * e for e in residuals) / len(residuals))
    return Fix(x, y, radius, rms, tuple(ranges))
