"""Ubicación de entidades a partir del RSSI de varios receptores.

Solo se ubican entidades con LAB-ID (dispositivos propios, informe §8). El
resto no se posiciona, ni siquiera internamente.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from ..track.presence import Entity
from .room import Room
from .trilateration import MIN_NODES, make_range, trilaterate

FRESH_S = 10.0  # un receptor aporta solo si escuchó a la entidad en los últimos N s


class Locator:
    def __init__(self, room: Room) -> None:
        self.room = room

    def ranges_for(self, entity: Entity, now: datetime) -> list:
        ranges = []
        for node_id, tracker in entity.node_rssi.items():
            node = self.room.nodes.get(node_id)
            last = entity.node_last.get(node_id)
            state = tracker.state()
            if node is None or last is None or state.smoothed is None:
                continue
            if (now - last).total_seconds() > FRESH_S:
                continue
            spread_sigma = state.spread / 1.35 if state.spread is not None else None  # IQR → σ
            ranges.append(make_range(node_id, node.x, node.y, state.smoothed, node.ref_dbm, node.n, spread_sigma))
        return ranges

    def locate(self, entity: Entity, now: datetime) -> dict[str, Any]:
        ranges = self.ranges_for(entity, now)
        out: dict[str, Any] = {
            "id": entity.id,
            "lab_id": entity.lab_id,
            "nodes_used": [r.node for r in ranges],
            "ranges": [{"node": r.node, "d": round(r.distance, 2), "sigma": round(r.sigma, 2)} for r in ranges],
            "x": None,
            "y": None,
            "radius": None,
        }
        if len(ranges) < MIN_NODES:
            out["status"] = f"insuficiente: {len(ranges)} de {MIN_NODES} receptores con señal reciente"
            return out
        fix = trilaterate(ranges, self.room.width, self.room.height)
        if fix is None:
            out["status"] = "geometría degenerada (receptores alineados)"
            return out
        out.update(
            x=round(fix.x, 2),
            y=round(fix.y, 2),
            radius=round(fix.radius, 2),
            residual_rms=round(fix.residual_rms, 2),
            status="estimada",
        )
        return out

    def calibrate(self, entity: Entity, node_id: str, distance_m: float) -> dict[str, Any]:
        """Calibración de un punto: fija ref_dbm (RSSI a 1 m) con el dispositivo a `distance_m` del receptor."""
        node = self.room.nodes.get(node_id)
        tracker = entity.node_rssi.get(node_id)
        if node is None:
            raise ValueError(f"Receptor desconocido: {node_id}")
        if tracker is None or tracker.state().smoothed is None:
            raise ValueError(f"El receptor {node_id} no tiene señal de esta entidad")
        if distance_m <= 0:
            raise ValueError("La distancia debe ser positiva")
        rssi = tracker.state().smoothed
        node.ref_dbm = rssi + 10 * node.n * math.log10(distance_m)
        node.calibrated = True
        self.room.save()
        return {"node": node_id, "rssi": round(rssi, 1), "distance_m": distance_m, "ref_dbm": round(node.ref_dbm, 1)}
