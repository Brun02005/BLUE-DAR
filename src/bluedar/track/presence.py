"""Entidades por sesión: aparición, desaparición y estado acumulado.

La entidad es (dirección pseudonimizada, sesión). No se vinculan direcciones
rotadas entre sí: un dispositivo que cambia de RPA aparece como una entidad
nueva y la anterior pasa a "ausente". Por eso el conteo puede sobreestimar.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime

from ..capture.base import Observation
from ..classify.evidence import EntityEvidence
from ..classify.rules_engine import Evidence
from ..decode.ad_structures import Decoded
from ..proximity.rssi import RssiTracker

DEFAULT_ABSENCE_S = 30.0
HISTORY_POINTS = 900  # 15 min a 1 punto/s


@dataclass(slots=True)
class Entity:
    id: str
    transport: str
    address_kind: str
    first_seen: datetime
    last_seen: datetime
    packets: int = 0
    present: bool = True
    has_payload: bool = False
    has_name: bool = False
    name_hint: str | None = None
    lab_id: str | None = None
    pdus: Counter = field(default_factory=Counter)
    companies: set[int] = field(default_factory=set)
    apple_types: set[int] = field(default_factory=set)
    # `rssi` sigue al receptor principal (el de esta máquina); `node_rssi`, a cada receptor.
    rssi: RssiTracker = field(default_factory=RssiTracker)
    rssi_last: int | None = None
    node_rssi: dict[str, RssiTracker] = field(default_factory=dict)
    node_last: dict[str, datetime] = field(default_factory=dict)
    evidence: EntityEvidence = field(default_factory=EntityEvidence)
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_POINTS))

    def record(self, obs: Observation, decoded: Decoded, evidences: list[Evidence], primary_node: str = "local") -> None:
        self.packets += 1
        self.last_seen = obs.t
        self.present = True
        self.pdus[obs.pdu or "?"] += 1
        self.has_name = self.has_name or obs.has_name
        self.name_hint = obs.name_hint or self.name_hint
        self.companies.update(decoded.manufacturer)
        self.apple_types.update(m.type for m in decoded.apple)
        if any(s.type != 0x01 for s in obs.ad) or obs.cod is not None:
            self.has_payload = True
        if obs.rssi is not None and obs.rssi > -127:
            ts = obs.t.timestamp()
            self.node_rssi.setdefault(obs.node, RssiTracker()).add(ts, obs.rssi)
            self.node_last[obs.node] = obs.t
            if obs.node == primary_node:
                self._record_primary_rssi(ts, obs.rssi)
        self.evidence.add(evidences, obs.t)

    def _record_primary_rssi(self, ts: float, rssi: int) -> None:
        self.rssi.add(ts, rssi)
        self.rssi_last = rssi
        smoothed = self.rssi.state().smoothed
        second = int(ts)
        if self.history and self.history[-1][0] == second:
            self.history[-1] = (second, smoothed)
        else:
            self.history.append((second, smoothed))


class PresenceTracker:
    def __init__(self, absence_s: float = DEFAULT_ABSENCE_S, primary_node: str = "local") -> None:
        self.absence_s = absence_s
        self.primary_node = primary_node
        self.entities: dict[str, Entity] = {}

    def observe(self, obs: Observation, decoded: Decoded, evidences: list[Evidence]) -> tuple[Entity, str | None]:
        """Devuelve la entidad y el evento ("nuevo", "reaparece" o None)."""
        entity = self.entities.get(obs.address)
        event = None
        if entity is None:
            entity = Entity(obs.address, obs.transport, obs.address_kind, obs.t, obs.t)
            self.entities[obs.address] = entity
            event = "nuevo"
        elif not entity.present:
            event = "reaparece"
        entity.record(obs, decoded, evidences, self.primary_node)
        return entity, event

    def sweep(self, now: datetime) -> list[Entity]:
        """Marca como ausentes las entidades sin paquetes en `absence_s`. Devuelve las que cambiaron."""
        gone = []
        for entity in self.entities.values():
            if entity.present and (now - entity.last_seen).total_seconds() > self.absence_s:
                entity.present = False
                gone.append(entity)
        return gone
