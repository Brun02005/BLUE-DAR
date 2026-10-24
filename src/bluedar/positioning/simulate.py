"""Monte Carlo: qué precisión cabe esperar de una configuración de receptores
ANTES de comprar hardware. Los resultados son de un modelo, no mediciones:
el sombreado real en interiores no es gaussiano ni independiente entre
receptores, así que estos números son una cota optimista.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass

from .room import Room
from .trilateration import make_range, trilaterate


@dataclass(frozen=True, slots=True)
class SimResult:
    sigma_db: float
    n_true: float
    trials: int
    solved: int
    median_m: float
    p90_m: float
    mean_reported_radius_m: float
    coverage: float  # fracción de casos con error ≤ radio informado
    center_median_m: float  # línea de base: decir siempre "el centro de la habitación"
    center_p90_m: float


def run(room: Room, sigma_db: float, n_true: float | None = None, trials: int = 500, seed: int = 7) -> SimResult:
    rng = random.Random(seed)
    nodes = list(room.nodes.values())
    errors, radii, covered, center_errors = [], [], 0, []
    for _ in range(trials):
        tx, ty = rng.uniform(0, room.width), rng.uniform(0, room.height)
        center_errors.append(math.hypot(tx - room.width / 2, ty - room.height / 2))
        ranges = []
        for node in nodes:
            d = max(0.3, math.hypot(tx - node.x, ty - node.y))
            n = n_true if n_true is not None else node.n
            rssi = node.ref_dbm - 10 * n * math.log10(d) + rng.gauss(0, sigma_db)
            ranges.append(make_range(node.id, node.x, node.y, rssi, node.ref_dbm, node.n, sigma_db))
        fix = trilaterate(ranges, room.width, room.height)
        if fix is None:
            continue
        err = math.hypot(fix.x - tx, fix.y - ty)
        errors.append(err)
        radii.append(fix.radius)
        covered += err <= fix.radius
    if not errors:
        return SimResult(sigma_db, n_true or 0, trials, 0, math.nan, math.nan, math.nan, 0.0, math.nan, math.nan)
    return SimResult(
        sigma_db=sigma_db,
        n_true=n_true if n_true is not None else statistics.mean(n.n for n in nodes),
        trials=trials,
        solved=len(errors),
        median_m=statistics.median(errors),
        p90_m=statistics.quantiles(errors, n=10)[-1],
        mean_reported_radius_m=statistics.mean(radii),
        coverage=covered / len(errors),
        center_median_m=statistics.median(center_errors),
        center_p90_m=statistics.quantiles(center_errors, n=10)[-1],
    )
