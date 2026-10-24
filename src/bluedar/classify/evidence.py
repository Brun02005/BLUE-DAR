"""Acumulación de evidencias por entidad y decisión de etiqueta.

Reglas inviolables (informe §2): el RSSI nunca entra acá, y un Company ID o un
dato desconocido nunca produce "posible auricular/parlante" por sí solo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .rules_engine import Evidence, Rule

AUDIO_TYPES = ("auricular", "parlante")
LABELS = {
    "auricular": "posible auricular",
    "parlante": "posible parlante",
    "desconocido": "dispositivo desconocido",
    "insuficiente": "clasificación insuficiente",
}
MIN_CONSISTENT_PACKETS = 3


@dataclass(slots=True)
class EvidenceAgg:
    rule: Rule
    type: str | None
    detail: str
    family: str
    count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    models: set[str] = field(default_factory=set)
    model_keys: set[str] = field(default_factory=set)


@dataclass(slots=True)
class Classification:
    label: str  # clave de LABELS
    confidence: str | None  # alta | media | baja | None
    basis: str | None  # "declarado" | "hipótesis" | None
    family: str | None
    model: str | None
    reasons: list[dict]
    warnings: list[str]

    @property
    def label_text(self) -> str:
        return LABELS[self.label]


class EntityEvidence:
    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str | None], EvidenceAgg] = {}

    def add(self, evidences: list[Evidence], t: datetime) -> None:
        for ev in evidences:
            key = (ev.rule.id, ev.type)
            agg = self.by_key.get(key)
            if agg is None:
                agg = self.by_key[key] = EvidenceAgg(ev.rule, ev.type, ev.finding.detail, ev.family, first_seen=t)
            agg.count += 1
            agg.last_seen = t
            agg.detail = ev.finding.detail
            if ev.finding.model:
                agg.models.add(ev.finding.model)
            if ev.finding.model_key:
                agg.model_keys.add(ev.finding.model_key)

    def classify(self, packets: int, has_payload: bool) -> Classification:
        aggs = sorted(self.by_key.values(), key=lambda a: (a.rule.level_rank, -a.count))
        reasons = [_reason(a) for a in aggs]
        warnings: list[str] = []

        model_keys = set().union(*(a.model_keys for a in aggs)) if aggs else set()
        if len(model_keys) > 1:
            warnings.append(
                "La misma dirección declaró modelos distintos ("
                + ", ".join(sorted(model_keys))
                + "): posible falsificación."
            )
        models = sorted(set().union(*(a.models for a in aggs))) if aggs else []
        model = models[0] if len(models) == 1 else None

        audio = [a for a in aggs if a.type in AUDIO_TYPES]
        audio_types = {a.type for a in audio}
        non_audio = [a for a in aggs if a.type == "no_audio"]
        generic_audio = [a for a in aggs if a.type == "audio"]
        family = next((a.family for a in aggs), None)

        if audio:
            if len(audio_types) > 1:
                return Classification(
                    "insuficiente", None, None, family, model, reasons,
                    warnings + ["Evidencias contradictorias: auricular y parlante."],
                )
            if non_audio:
                return Classification(
                    "insuficiente", None, None, family, model, reasons,
                    warnings + ["La misma dirección tiene evidencia de audio y de dispositivo no-audio."],
                )
            best = audio[0]
            basis = "hipótesis" if best.rule.level == "heuristico" else "declarado"
            return Classification(
                best.type, _confidence(best), basis, best.family, model, reasons, warnings
            )

        if generic_audio:
            return Classification(
                "insuficiente", None, None, generic_audio[0].family, model, reasons,
                warnings + ["Hay indicios de audio, pero ningún campo declara si es auricular o parlante."],
            )
        if aggs:
            return Classification("desconocido", None, None, family, model, reasons, warnings)
        if packets < MIN_CONSISTENT_PACKETS or not has_payload:
            return Classification(
                "insuficiente", None, None, None, None, reasons,
                warnings + ["Pocos paquetes o anuncio sin datos clasificables."],
            )
        return Classification("desconocido", None, None, None, None, reasons, warnings)


def _confidence(best: EvidenceAgg) -> str:
    consistent = best.count >= MIN_CONSISTENT_PACKETS
    rank = best.rule.level_rank
    validated = best.rule.validated or {}
    if not consistent or best.rule.level == "heuristico":
        return "baja"
    if rank <= 1:
        return "alta"
    if validated.get("precision", 0) >= 0.9:
        return "alta"
    return "media"


def _reason(a: EvidenceAgg) -> dict:
    return {
        "rule": a.rule.id,
        "level": a.rule.level,
        "type": a.type,
        "detail": a.detail,
        "packets": a.count,
        "source": a.rule.source,
        "false_positives": a.rule.false_positives,
        "validated": a.rule.validated is not None,
    }
