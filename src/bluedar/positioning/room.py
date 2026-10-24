"""Configuración de la habitación: tamaño y receptores en posiciones conocidas (metros)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Valores provisionales del modelo log-distancia hasta calibrar cada receptor.
DEFAULT_REF_DBM = -59.0  # RSSI esperado a 1 m
DEFAULT_PATH_LOSS_N = 2.5  # 2 en espacio libre, 2.5–4 en interiores


@dataclass(slots=True)
class NodeConfig:
    id: str
    x: float
    y: float
    ref_dbm: float = DEFAULT_REF_DBM
    n: float = DEFAULT_PATH_LOSS_N
    calibrated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "ref_dbm": round(self.ref_dbm, 1), "n": self.n, "calibrated": self.calibrated}


@dataclass(slots=True)
class Room:
    width: float
    height: float
    nodes: dict[str, NodeConfig] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> Room:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        room = doc.get("room", {})
        nodes = {}
        for node_id, cfg in (doc.get("nodes") or {}).items():
            nodes[str(node_id)] = NodeConfig(
                id=str(node_id),
                x=float(cfg["x"]),
                y=float(cfg["y"]),
                ref_dbm=float(cfg.get("ref_dbm", DEFAULT_REF_DBM)),
                n=float(cfg.get("n", DEFAULT_PATH_LOSS_N)),
                calibrated=bool(cfg.get("calibrated", False)),
            )
        result = cls(float(room["width_m"]), float(room["height_m"]), nodes, path)
        result.validate()
        return result

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("La habitación necesita width_m y height_m positivos")
        for node in self.nodes.values():
            if not (0 <= node.x <= self.width and 0 <= node.y <= self.height):
                raise ValueError(f"El nodo {node.id} está fuera de la habitación")
            if node.n <= 0:
                raise ValueError(f"El nodo {node.id} tiene un exponente n inválido")

    def save(self) -> None:
        if self.path is None:
            return
        doc = {
            "room": {"width_m": self.width, "height_m": self.height},
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
        }
        self.path.write_text(
            "# Generado/actualizado por bluedar (calibración). Coordenadas en metros.\n"
            + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
        }
