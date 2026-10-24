"""Exportación de resultados por entidad a CSV o JSON."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

CSV_COLUMNS = [
    "id", "lab_id", "transport", "address_kind", "label_text", "confidence", "basis",
    "family", "model", "signal", "rssi", "spread", "trend", "packets", "rate",
    "first_seen", "last_seen", "present", "companies", "apple_types", "has_name",
    "name_hint", "rules", "warnings",
]


def entities_to_csv(entities: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for e in entities:
        row = dict(e)
        row["companies"] = "; ".join(e.get("companies", []))
        row["apple_types"] = "; ".join(e.get("apple_types", []))
        row["warnings"] = " | ".join(e.get("warnings", []))
        row["rules"] = "; ".join(f"{r['rule']}({r['level']}, {r['packets']})" for r in e.get("reasons", []))
        writer.writerow(row)
    return buf.getvalue()


def snapshot_to_json(snapshot: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    doc = {"meta": meta or {}, **snapshot}
    return json.dumps(doc, indent=2, ensure_ascii=False, default=str)
