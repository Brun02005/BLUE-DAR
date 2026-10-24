"""Receptor remoto: escanea BLE en esta máquina y envía las observaciones a un hub.

La pseudonimización ocurre acá, con la clave de sesión que entrega el hub al
registrarse: la dirección real del dispositivo nunca sale de esta máquina.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .capture.bleak_backend import BleakBackend
from .classify.rules_engine import load_default_ruleset
from .privacy.pseudonym import Privacy
from .store.jsonl_log import to_record

log = logging.getLogger(__name__)

SEND_EVERY_S = 0.5
MAX_BUFFER = 5000
BATCH = 1500


def _post(url: str, payload: dict[str, Any], token: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


class RemoteNode:
    def __init__(self, hub: str, node_id: str, scanning_mode: str = "active") -> None:
        self.hub = hub.rstrip("/")
        self.node_id = node_id
        self.scanning_mode = scanning_mode
        self.buffer: list[dict[str, Any]] = []
        self.sent = 0
        self.dropped = 0
        self.token: str | None = None
        self.privacy: Privacy | None = None

    def register(self) -> None:
        reply = _post(f"{self.hub}/api/nodes/register", {"node_id": self.node_id})
        self.token = reply["token"]
        ruleset = load_default_ruleset()
        self.privacy = Privacy(name_hinter=ruleset.name_hint, key=bytes.fromhex(reply["key"]))

    async def _sender(self) -> None:
        url = f"{self.hub}/api/nodes/{self.node_id}/observations"
        while True:
            await asyncio.sleep(SEND_EVERY_S)
            if not self.buffer:
                continue
            batch, self.buffer = self.buffer[:BATCH], self.buffer[BATCH:]
            try:
                await asyncio.to_thread(_post, url, {"records": batch}, self.token)
                self.sent += len(batch)
            except urllib.error.HTTPError as exc:
                if exc.code == 401:  # el hub se reinició: volver a registrarse
                    await asyncio.to_thread(self.register)
                self.dropped += len(batch)
                log.warning("El hub rechazó un lote (%s)", exc.code)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self.dropped += len(batch)
                log.warning("No se pudo enviar al hub: %s", exc)

    async def _reporter(self) -> None:
        while True:
            await asyncio.sleep(5)
            print(f"[{self.node_id}] enviados={self.sent} descartados={self.dropped} en cola={len(self.buffer)}", flush=True)

    async def run(self) -> None:
        await asyncio.to_thread(self.register)
        print(f"Nodo '{self.node_id}' registrado en {self.hub}")
        backend = BleakBackend(self.scanning_mode)
        tasks = [asyncio.create_task(self._sender()), asyncio.create_task(self._reporter())]
        try:
            async for obs in backend.observations():
                assert self.privacy is not None
                if len(self.buffer) >= MAX_BUFFER:
                    self.dropped += 1
                    continue
                self.buffer.append(to_record(self.privacy.apply(obs)))
        finally:
            for task in tasks:
                task.cancel()
