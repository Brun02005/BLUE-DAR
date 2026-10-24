"""Carga de reglas (YAML) y evaluación por paquete.

Las reglas son datos; los detectores son funciones puras que miran un paquete
decodificado y devuelven un `Finding` o None.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

import yaml

from ..capture.base import Observation
from ..decode.ad_structures import Decoded
from ..decode.apple_continuity import FIND_MY, PROXIMITY_PAIRING, ContinuityMessage
from ..decode.class_of_device import describe_appearance, describe_cod

LEVELS = ("estandar", "fabricante_doc", "fabricante_re", "heuristico")
TYPES = ("auricular", "parlante", "audio", "no_audio", None)


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    detector: str
    params: dict[str, Any]
    claim_type: str | None
    family: str
    level: str
    source: str
    false_positives: str
    validated: dict[str, Any] | None

    @property
    def level_rank(self) -> int:
        return LEVELS.index(self.level)


@dataclass(frozen=True, slots=True)
class Finding:
    """Resultado de un detector. `type` reemplaza al de la regla si no es None."""

    detail: str
    type: str | None = None
    model: str | None = None  # p. ej. "AirPods Pro (0e20)" o "no tabulado (0e21)"
    model_key: str | None = None
    family: str | None = None  # reemplaza a la familia de la regla si es más específica


@dataclass(frozen=True, slots=True)
class Evidence:
    rule: Rule
    finding: Finding

    @property
    def type(self) -> str | None:
        return self.finding.type or self.rule.claim_type

    @property
    def family(self) -> str:
        return self.finding.family or self.rule.family


@dataclass(slots=True)
class RuleSet:
    rules: list[Rule]
    name_hints: dict[str, list[str]]
    spam: dict[str, Any]
    apple_models: dict[str, dict[str, Any]] = field(default_factory=dict)
    fastpair_models: dict[str, dict[str, Any]] = field(default_factory=dict)
    companies: dict[int, str] = field(default_factory=dict)

    def name_hint(self, name: str) -> str | None:
        lowered = name.lower()
        for kind, words in self.name_hints.items():
            for word in words:
                if word in lowered:
                    return f"{kind}:{word}"
        return None

    def evaluate(self, obs: Observation, decoded: Decoded) -> list[Evidence]:
        out: list[Evidence] = []
        for rule in self.rules:
            finding = DETECTORS[rule.detector](self, rule.params, obs, decoded)
            if finding is not None:
                out.append(Evidence(rule, finding))
        return out


# --- detectores --------------------------------------------------------------

Detector = Callable[[RuleSet, dict[str, Any], Observation, Decoded], Finding | None]


def _apple_continuity(rs: RuleSet, params: dict[str, Any], _obs: Observation, d: Decoded) -> Finding | None:
    wanted = set(params["types"])
    hits = [m for m in d.apple if m.type in wanted]
    if not hits:
        return None
    names = ", ".join(sorted({f"{m.type_name} (0x{m.type:02X})" for m in hits}))
    find_my = next((m for m in hits if m.type == FIND_MY), None)
    if find_my is not None:
        return _find_my_finding(names, find_my)
    model_msg = next((m for m in hits if m.type == PROXIMITY_PAIRING and m.model), None)
    if model_msg is None:
        return Finding(detail=f"Apple Continuity: {names}")
    entry = rs.apple_models.get(model_msg.model)
    if entry:
        return Finding(
            detail=f"Apple Continuity: {names}; modelo declarado 0x{model_msg.model}",
            type=entry.get("type"),
            model=f"{entry['name']} (0x{model_msg.model})",
            model_key=model_msg.model,
        )
    return Finding(
        detail=f"Apple Continuity: {names}; modelo 0x{model_msg.model} no tabulado",
        model=f"no tabulado (0x{model_msg.model})",
        model_key=model_msg.model,
    )


def _find_my_finding(names: str, msg: ContinuityMessage) -> Finding:
    """Find My: pista de tipo y estado, sin declarar tipo de audio (bits no validados en laboratorio)."""
    state = "separado del dueño" if msg.separated else "cerca del dueño"
    if msg.find_my_hint:
        family = f"Apple Find My · pista: {msg.find_my_hint} · {state}"
        detail = (
            f"Apple Continuity: {names}; status byte indica {msg.find_my_hint} (según AirGuard), {state}. "
            "La clave rota cada ~15 min: indica el tipo, no cuál dispositivo es."
        )
    else:
        family = f"Apple Find My (tipo no determinable) · {state}"
        detail = f"Apple Continuity: {names}; {state}"
    return Finding(detail=detail, family=family)


def _fast_pair(rs: RuleSet, params: dict[str, Any], _obs: Observation, d: Decoded) -> Finding | None:
    fp = d.fast_pair
    if fp is None or fp.discoverable != params["discoverable"]:
        return None
    if fp.model_id is None:
        return Finding(detail="Fast Pair (0xFE2C) sin Model ID: fuera de modo emparejamiento")
    entry = rs.fastpair_models.get(fp.model_id)
    if entry:
        return Finding(
            detail=f"Fast Pair Model ID 0x{fp.model_id}",
            type=entry.get("type"),
            model=f"{entry['name']} (0x{fp.model_id})",
            model_key=fp.model_id,
        )
    return Finding(
        detail=f"Fast Pair Model ID 0x{fp.model_id} no tabulado",
        model=f"no tabulado (0x{fp.model_id})",
        model_key=fp.model_id,
    )


def _swift_pair(_rs: RuleSet, params: dict[str, Any], _obs: Observation, d: Decoded) -> Finding | None:
    sp = d.swift_pair
    if sp is None:
        return None
    if params["require_cod"]:
        if sp.cod is None:
            return None
        text, kind = describe_cod(sp.cod)
        return Finding(
            detail=f"Swift Pair {sp.scenario_name}; CoD 0x{sp.cod:06X} = {text}",
            type=kind,
            family=f"Swift Pair · {text}",
        )
    if sp.cod is not None:
        return None  # lo cubre la variante con CoD
    return Finding(detail=f"Swift Pair {sp.scenario_name} sin CoD")


def _appearance(_rs: RuleSet, _params: dict[str, Any], _obs: Observation, d: Decoded) -> Finding | None:
    if d.appearance is None:
        return None
    text, kind = describe_appearance(d.appearance)
    return Finding(detail=f"Appearance 0x{d.appearance:04X} = {text}", type=kind, family=text)


def _class_of_device(_rs: RuleSet, _params: dict[str, Any], _obs: Observation, d: Decoded) -> Finding | None:
    if d.cod is None:
        return None
    text, kind = describe_cod(d.cod)
    return Finding(detail=f"CoD 0x{d.cod:06X} = {text}", type=kind, family=f"Classic · {text}")


def _service_uuid16(_rs: RuleSet, params: dict[str, Any], _obs: Observation, d: Decoded) -> Finding | None:
    present = (d.uuids16 | set(d.service_data16)) & set(params["uuids"])
    if not present:
        return None
    return Finding(detail="UUID de servicio " + ", ".join(f"0x{u:04X}" for u in sorted(present)))


def _name_hint(_rs: RuleSet, _params: dict[str, Any], obs: Observation, _d: Decoded) -> Finding | None:
    if not obs.name_hint:
        return None
    kind, _, word = obs.name_hint.partition(":")
    return Finding(detail=f"El nombre local contiene '{word}'", type=kind)


DETECTORS: dict[str, Detector] = {
    "apple_continuity": _apple_continuity,
    "fast_pair": _fast_pair,
    "swift_pair": _swift_pair,
    "appearance": _appearance,
    "class_of_device": _class_of_device,
    "service_uuid16": _service_uuid16,
    "name_hint": _name_hint,
}


# --- carga -------------------------------------------------------------------


def _load_yaml(name: str) -> dict[str, Any]:
    text = resources.files("bluedar.rules").joinpath(name).read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def parse_rules(doc: dict[str, Any]) -> list[Rule]:
    rules: list[Rule] = []
    seen: set[str] = set()
    for raw in doc.get("rules", []):
        rid = raw["id"]
        if rid in seen:
            raise ValueError(f"Regla duplicada: {rid}")
        seen.add(rid)
        if raw["detector"] not in DETECTORS:
            raise ValueError(f"{rid}: detector desconocido {raw['detector']!r}")
        if raw["level"] not in LEVELS:
            raise ValueError(f"{rid}: nivel inválido {raw['level']!r}")
        claim = raw.get("claim", {})
        if claim.get("type") not in TYPES:
            raise ValueError(f"{rid}: tipo inválido {claim.get('type')!r}")
        rules.append(
            Rule(
                id=rid,
                detector=raw["detector"],
                params=raw.get("params") or {},
                claim_type=claim.get("type"),
                family=claim.get("family", ""),
                level=raw["level"],
                source=raw.get("source", ""),
                false_positives=raw.get("false_positives", ""),
                validated=raw.get("validated"),
            )
        )
    return rules


@cache
def load_default_ruleset() -> RuleSet:
    doc = _load_yaml("classification.yaml")
    return RuleSet(
        rules=parse_rules(doc),
        name_hints=doc.get("name_hints", {}),
        spam=doc.get("spam", {}),
        apple_models={str(k): v for k, v in (_load_yaml("apple_models.yaml").get("models") or {}).items()},
        fastpair_models={str(k): v for k, v in (_load_yaml("fastpair_models.yaml").get("models") or {}).items()},
        companies={int(k): v for k, v in (_load_yaml("company_ids.yaml").get("companies") or {}).items()},
    )
