"""Estadísticas de captura por dirección (experimento E1: capacidad de la plataforma)."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..decode.ad_structures import decode
from ..store.jsonl_log import read_jsonl


@dataclass(slots=True)
class AddrStats:
    addr: str
    kind: str
    transport: str
    times: list[float] = field(default_factory=list)
    rssi: list[int] = field(default_factory=list)
    pdus: Counter = field(default_factory=Counter)
    companies: set[int] = field(default_factory=set)
    apple: set[str] = field(default_factory=set)
    has_name: set[str] = field(default_factory=set)

    def row(self) -> dict:
        times = sorted(self.times)
        gaps = [b - a for a, b in zip(times, times[1:])]
        duration = times[-1] - times[0] if len(times) > 1 else 0.0
        return {
            "addr": self.addr,
            "kind": self.kind,
            "tr": self.transport,
            "packets": len(times),
            "duration_s": round(duration, 1),
            "rate_hz": round((len(times) - 1) / duration, 2) if duration > 0 else None,
            "gap_p50_s": round(statistics.median(gaps), 3) if gaps else None,
            "gap_max_s": round(max(gaps), 2) if gaps else None,
            "rssi_med": statistics.median(self.rssi) if self.rssi else None,
            "rssi_min": min(self.rssi) if self.rssi else None,
            "rssi_max": max(self.rssi) if self.rssi else None,
            "pdus": dict(self.pdus),
            "companies": [f"0x{c:04X}" for c in sorted(self.companies)],
            "apple": sorted(self.apple),
            "name_in": sorted(self.has_name),
        }


def compute(path: Path) -> tuple[dict, list[dict]]:
    per: dict[str, AddrStats] = {}
    first = last = None
    total = 0
    pdu_total: Counter = Counter()
    for obs in read_jsonl(path):
        total += 1
        ts = obs.t.timestamp()
        first = ts if first is None else min(first, ts)
        last = ts if last is None else max(last, ts)
        s = per.get(obs.address)
        if s is None:
            s = per[obs.address] = AddrStats(obs.address, obs.address_kind, obs.transport)
        s.times.append(ts)
        if obs.rssi is not None:
            s.rssi.append(obs.rssi)
        s.pdus[obs.pdu or "?"] += 1
        pdu_total[obs.pdu or "?"] += 1
        d = decode(obs)
        s.companies.update(d.manufacturer)
        for m in d.apple:
            s.apple.add(f"0x{m.type:02X}" + (f"(modelo {m.model})" if m.model else ""))
        if obs.has_name:
            s.has_name.add(obs.pdu or "?")
    duration = (last - first) if first is not None and last is not None else 0.0
    summary = {
        "file": str(path),
        "packets": total,
        "duration_s": round(duration, 1),
        "packets_per_s": round(total / duration, 1) if duration > 0 else None,
        "addresses": len(per),
        "address_kinds": dict(Counter(s.kind for s in per.values())),
        "pdus": dict(pdu_total),
    }
    rows = sorted((s.row() for s in per.values()), key=lambda r: -r["packets"])
    return summary, rows
