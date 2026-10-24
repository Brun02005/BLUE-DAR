"""Registro append-only de observaciones en JSONL (una línea por paquete).

Formato v1 (ver docs/formato-captura.md). Solo se escriben observaciones que
ya pasaron por la capa de privacidad.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from ..capture.base import AdStructure, Observation

FORMAT_VERSION = 1


def to_record(obs: Observation) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "v": FORMAT_VERSION,
        "t": obs.t.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "tr": obs.transport,
        "addr": obs.address,
        "kind": obs.address_kind,
        "rssi": obs.rssi,
        "pdu": obs.pdu,
        "be": obs.backend,
    }
    for key, value in (
        ("conn", obs.connectable),
        ("scan", obs.scannable),
        ("dir", obs.directed),
        ("tx", obs.tx_power),
        ("cod", obs.cod),
        ("name", obs.name),
        ("hint", obs.name_hint),
    ):
        if value is not None:
            rec[key] = value
    if obs.has_name:
        rec["has_name"] = True
    if obs.node != "local":
        rec["node"] = obs.node
    if obs.ad:
        rec["ad"] = [
            [s.type, s.data.hex()] if s.data is not None else [s.type, None, s.length] for s in obs.ad
        ]
    if obs.extra.get("synthesized"):
        rec["syn"] = True
    return rec


def from_record(rec: dict[str, Any]) -> Observation:
    if rec.get("v") != FORMAT_VERSION:
        raise ValueError(f"Versión de formato no soportada: {rec.get('v')!r}")
    ad = tuple(
        AdStructure.of(item[0], bytes.fromhex(item[1]))
        if item[1] is not None
        else AdStructure(item[0], None, item[2])
        for item in rec.get("ad", [])
    )
    return Observation(
        t=datetime.fromisoformat(rec["t"].replace("Z", "+00:00")),
        transport=rec["tr"],
        address=rec["addr"],
        address_kind=rec["kind"],
        rssi=rec.get("rssi"),
        backend=rec.get("be", "?"),
        pdu=rec.get("pdu"),
        connectable=rec.get("conn"),
        scannable=rec.get("scan"),
        directed=rec.get("dir"),
        tx_power=rec.get("tx"),
        ad=ad,
        cod=rec.get("cod"),
        name=rec.get("name"),
        name_hint=rec.get("hint"),
        has_name=rec.get("has_name", False),
        node=rec.get("node", "local"),
        extra={"synthesized": True} if rec.get("syn") else {},
    )


class JsonlWriter:
    """Escritura con buffer; `flush()` se llama periódicamente desde el pipeline.
    Si el proceso muere se pierde como máximo lo no volcado desde el último flush."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh: IO[str] = path.open("a", encoding="utf-8")
        self.count = 0

    def write(self, obs: Observation) -> None:
        self._fh.write(json.dumps(to_record(obs), separators=(",", ":")) + "\n")
        self.count += 1

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def read_jsonl(path: Path) -> Iterator[Observation]:
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield from_record(json.loads(line))
            except (ValueError, KeyError) as exc:
                raise ValueError(f"{path}:{lineno}: registro inválido: {exc}") from exc


def write_meta(path: Path, meta: dict[str, Any]) -> None:
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def meta_path_for(jsonl_path: Path) -> Path:
    return jsonl_path.with_suffix(".meta.json")
