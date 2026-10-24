"""Registro de receptores (nodos) que envían observaciones al hub."""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@dataclass(slots=True)
class NodeState:
    id: str
    token: str | None  # None para el receptor local
    packets: int = 0
    last_seen: datetime | None = None


class NodeRegistry:
    def __init__(self) -> None:
        self.nodes: dict[str, NodeState] = {}

    def register(self, node_id: str) -> str:
        if not NODE_ID_RE.match(node_id) or node_id == "local":
            raise ValueError("node_id inválido (letras, números, - y _; hasta 32; 'local' está reservado)")
        token = secrets.token_hex(16)
        state = self.nodes.get(node_id)
        if state is None:
            self.nodes[node_id] = NodeState(node_id, token)
        else:
            state.token = token  # re-registro tras reiniciar el nodo
        return token

    def check(self, node_id: str, token: str) -> bool:
        state = self.nodes.get(node_id)
        return bool(state and state.token and hmac.compare_digest(state.token, token))

    def seen(self, node_id: str, t: datetime) -> None:
        state = self.nodes.get(node_id)
        if state is None:
            state = self.nodes[node_id] = NodeState(node_id, None)
        state.packets += 1
        state.last_seen = t

    def status(self, now: datetime) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "packets": s.packets,
                "last_seen_s": round((now - s.last_seen).total_seconds(), 1) if s.last_seen else None,
                "remote": s.token is not None,
            }
            for s in self.nodes.values()
        ]
