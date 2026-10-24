"""Sesión de escaneo: une backends, privacidad, registro, clasificación,
presencia y proximidad. Todo corre en un único event loop de asyncio."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .capture.base import Backend, Observation
from .classify.rules_engine import RuleSet
from .decode.ad_structures import decode
from .decode.apple_continuity import PROXIMITY_PAIRING
from .nodes import NodeRegistry
from .positioning.engine import Locator
from .positioning.room import Room
from .privacy.pseudonym import Privacy
from .proximity.distance import estimate_distance
from .store.jsonl_log import JsonlWriter, from_record
from .track.presence import Entity, PresenceTracker

log = logging.getLogger(__name__)

TICK_S = 1.0
MAX_REMOTE_BATCH = 2000


class Session:
    def __init__(
        self,
        ruleset: RuleSet,
        privacy: Privacy | None = None,
        writer: JsonlWriter | None = None,
        absence_s: float = 30.0,
        clock: Callable[[], datetime] | None = None,
        meta: dict[str, Any] | None = None,
        virtual_time: bool = False,
        room: Room | None = None,
    ) -> None:
        """`virtual_time`: el "ahora" es la hora del último paquete (para replay)."""
        self.ruleset = ruleset
        self.privacy = privacy
        self.writer = writer
        self.tracker = PresenceTracker(absence_s)
        wall = clock or (lambda: datetime.now(UTC))
        self.clock = (lambda: self.last_obs_t or wall()) if virtual_time else wall
        self._virtual_time = virtual_time
        self.last_obs_t: datetime | None = None
        self.started = self.clock()
        self.meta: dict[str, Any] = meta or {}
        self.meta.setdefault("labels", {})
        self.events: deque[dict[str, Any]] = deque(maxlen=300)
        self.packets = 0
        self.backends: list[Backend] = []
        self._spam_window: deque[tuple[datetime, str]] = deque()
        self.spam_active = False
        self.nodes = NodeRegistry()
        self.room = room
        self.locator = Locator(room) if room else None

    # --- ingesta -------------------------------------------------------------

    def ingest(self, obs: Observation, already_private: bool = False) -> Entity:
        if not already_private:
            if self.privacy is None:
                raise RuntimeError("Observación en vivo sin capa de privacidad")
            obs = self.privacy.apply(obs)
        if self.writer is not None:
            self.writer.write(obs)
        decoded = decode(obs)
        evidences = self.ruleset.evaluate(obs, decoded)
        entity, event = self.tracker.observe(obs, decoded, evidences)
        if self.packets == 0 and self._virtual_time:
            self.started = obs.t
        self.nodes.seen(obs.node, obs.t)
        self.packets += 1
        self.last_obs_t = obs.t
        if event:
            if event == "nuevo" and entity.id in self.meta["labels"]:
                entity.lab_id = self.meta["labels"][entity.id]
            self._event(obs.t, event, entity)
        if any(m.type == PROXIMITY_PAIRING for m in decoded.apple):
            self._check_spam(obs.t, entity.id)
        return entity

    def _check_spam(self, t: datetime, entity_id: str) -> None:
        window = float(self.ruleset.spam.get("window_s", 10))
        limit = int(self.ruleset.spam.get("max_distinct_proximity_pairing_addresses", 6))
        self._spam_window.append((t, entity_id))
        while self._spam_window and (t - self._spam_window[0][0]).total_seconds() > window:
            self._spam_window.popleft()
        distinct = len({e for _, e in self._spam_window})
        active = distinct > limit
        if active and not self.spam_active:
            self.events.append({
                "t": _iso(t), "event": "alerta",
                "detail": f"{distinct} direcciones distintas emitieron Proximity Pairing en {window:.0f} s: posible BLE spam.",
            })
        self.spam_active = active

    # --- receptores remotos ----------------------------------------------------

    def register_node(self, node_id: str) -> dict[str, str]:
        """Da de alta un receptor remoto. Recibe la clave de sesión para pseudonimizar
        igual que el hub: la dirección real nunca sale del receptor que la escuchó."""
        if self.privacy is None:
            raise RuntimeError("Solo una sesión en vivo acepta receptores remotos")
        token = self.nodes.register(node_id)
        return {"token": token, "key": self.privacy.key_hex, "session_id": str(self.meta.get("session_id", ""))}

    def ingest_remote(self, node_id: str, token: str, records: list[dict[str, Any]]) -> int:
        if not self.nodes.check(node_id, token):
            raise PermissionError("Nodo no registrado o token inválido")
        if len(records) > MAX_REMOTE_BATCH:
            raise ValueError(f"Lote demasiado grande (máximo {MAX_REMOTE_BATCH})")
        now = self.clock()
        observations = []
        for rec in records:
            rec = {**rec, "v": rec.get("v", 1), "t": now.isoformat()}  # hora del hub: evita desfasajes de reloj
            obs = from_record(rec)
            obs.node = node_id
            observations.append(obs)
        for obs in observations:
            self.ingest(obs, already_private=True)
        return len(observations)

    # --- posiciones ------------------------------------------------------------

    def positions(self) -> list[dict[str, Any]]:
        if self.locator is None:
            return []
        now = self.clock()
        return [
            self.locator.locate(e, now)
            for e in self.tracker.entities.values()
            if e.lab_id and e.present
        ]

    def calibrate(self, entity_id: str, node_id: str, distance_m: float) -> dict[str, Any]:
        if self.locator is None:
            raise ValueError("No hay habitación configurada (--room)")
        entity = self.tracker.entities.get(entity_id)
        if entity is None or not entity.lab_id:
            raise ValueError("Solo se calibra con dispositivos propios (entidad con LAB-ID)")
        result = self.locator.calibrate(entity, node_id, distance_m)
        self.events.append({"t": _iso(self.clock()), "event": "calibración",
                            "detail": f"{node_id}: ref {result['ref_dbm']} dBm a 1 m"})
        return result

    def tick(self) -> None:
        now = self.clock()
        for entity in self.tracker.sweep(now):
            self._event(now, "ausente", entity)
        if self.spam_active and self._spam_window:
            window = float(self.ruleset.spam.get("window_s", 10))
            if (now - self._spam_window[-1][0]).total_seconds() > window:
                self.spam_active = False
        if self.writer is not None:
            self.writer.flush()

    def _event(self, t: datetime, kind: str, entity: Entity) -> None:
        self.events.append({"t": _iso(t), "event": kind, "entity": entity.id})

    # --- consultas -----------------------------------------------------------

    def label(self, entity_id: str, lab_id: str | None) -> bool:
        entity = self.tracker.entities.get(entity_id)
        if entity is None:
            return False
        entity.lab_id = lab_id or None
        if lab_id:
            self.meta["labels"][entity_id] = lab_id
        else:
            self.meta["labels"].pop(entity_id, None)
        return True

    def _distance(self, prox: Any) -> dict[str, Any] | None:
        if prox.smoothed is None:
            return None
        node = self.room.nodes.get("local") if self.room else None
        if node is not None and node.calibrated:
            est = estimate_distance(prox.smoothed, prox.spread, node.ref_dbm, node.n, calibrated=True)
        else:
            est = estimate_distance(prox.smoothed, prox.spread)
        return {
            "low": est.low_m, "high": est.high_m, "nominal": est.nominal_m,
            "calibrated": est.calibrated, "uncertain": est.uncertain, "text": est.text(),
        }

    def entity_summary(self, e: Entity, include_reasons: bool = True) -> dict[str, Any]:
        c = e.evidence.classify(e.packets, e.has_payload)
        prox = e.rssi.state()
        duration = max((e.last_seen - e.first_seen).total_seconds(), 1.0)
        warnings = list(c.warnings)
        if self.spam_active and PROXIMITY_PAIRING in e.apple_types:
            warnings.append("Hay una ráfaga de Proximity Pairing en el entorno (posible BLE spam).")
        out = {
            "id": e.id,
            "lab_id": e.lab_id,
            "transport": e.transport,
            "address_kind": e.address_kind,
            "label": c.label,
            "label_text": c.label_text,
            "confidence": c.confidence,
            "basis": c.basis,
            "family": c.family,
            "model": c.model,
            "signal": prox.category,
            "rssi": round(prox.smoothed, 1) if prox.smoothed is not None else None,
            "rssi_last": e.rssi_last,
            "spread": round(prox.spread, 1) if prox.spread is not None else None,
            "distance": self._distance(prox),
            "trend": prox.trend,
            "packets": e.packets,
            "rate": round(e.packets / duration, 2),
            "first_seen": _iso(e.first_seen),
            "last_seen": _iso(e.last_seen),
            "present": e.present,
            "companies": [self.ruleset.companies.get(cid, f"0x{cid:04X}") for cid in sorted(e.companies)],
            "apple_types": [f"0x{t:02X}" for t in sorted(e.apple_types)],
            "pdus": dict(e.pdus),
            "has_name": e.has_name,
            "name_hint": e.name_hint,
            "warnings": warnings,
        }
        if include_reasons:
            out["reasons"] = c.reasons
        return out

    def snapshot(self, include_reasons: bool = True) -> dict[str, Any]:
        entities = [self.entity_summary(e, include_reasons) for e in self.tracker.entities.values()]
        present = [e for e in entities if e["present"]]
        truth = next((b.truth for b in self.backends if getattr(b, "truth", None)), None)
        return {
            "t": _iso(self.clock()),
            "started": _iso(self.started),
            "packets": self.packets,
            "entities_total": len(entities),
            "entities_present": len(present),
            "spam_active": self.spam_active,
            "dropped": sum(getattr(b, "dropped", 0) for b in self.backends),
            "backends": [b.name for b in self.backends],
            "entities": entities,
            "events": list(self.events)[-50:],
            "nodes": self.nodes.status(self.clock()),
            "room": self.room.to_dict() if self.room else None,
            "positions": self.positions(),
            "truth": {k: list(v) for k, v in truth.items()} if truth else None,
        }

    def history(self, entity_id: str) -> list[tuple[int, float]] | None:
        entity = self.tracker.entities.get(entity_id)
        return list(entity.history) if entity else None

    # --- ejecución -----------------------------------------------------------

    async def consume(self, backend: Backend) -> None:
        self.backends.append(backend)
        private = getattr(backend, "already_private", False)
        async for obs in backend.observations():
            try:
                self.ingest(obs, already_private=private)
            except Exception:
                log.exception("Error procesando una observación de %s", backend.name)

    async def ticker(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            self.tick()


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")
