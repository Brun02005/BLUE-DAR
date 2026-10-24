"""Proximidad relativa a partir del RSSI (informe §7).

No convierte a metros: las categorías son de intensidad de señal para este
adaptador, con histéresis para que no oscilen. Los umbrales son provisionales
hasta calibrarlos con el experimento E4.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass

STRONG_DBM = -60.0
MEDIUM_DBM = -75.0
HYSTERESIS_DB = 3.0
MEDIAN_WINDOW_S = 5.0
SPREAD_WINDOW_S = 10.0
EMA_ALPHA = 0.3
TREND_WINDOW_S = 20.0
CATEGORIES = ("fuerte", "media", "débil")


@dataclass(frozen=True, slots=True)
class ProximityState:
    smoothed: float | None
    spread: float | None  # rango intercuartílico de las muestras recientes (dB)
    category: str | None
    trend: str | None  # acercándose | estable | alejándose | None (datos insuficientes)


class RssiTracker:
    def __init__(
        self,
        strong: float = STRONG_DBM,
        medium: float = MEDIUM_DBM,
        hysteresis: float = HYSTERESIS_DB,
    ) -> None:
        self.strong = strong
        self.medium = medium
        self.hysteresis = hysteresis
        self._samples: deque[tuple[float, int]] = deque()
        self._smoothed: float | None = None
        self._category: str | None = None
        self._history: deque[tuple[float, float]] = deque()

    def add(self, t: float, rssi: int) -> None:
        """`t` en segundos (monótono dentro de la sesión)."""
        self._samples.append((t, rssi))
        while self._samples and self._samples[0][0] < t - SPREAD_WINDOW_S:
            self._samples.popleft()
        recent = [r for ts, r in self._samples if ts >= t - MEDIAN_WINDOW_S]
        median = statistics.median(recent)
        self._smoothed = median if self._smoothed is None else (
            EMA_ALPHA * median + (1 - EMA_ALPHA) * self._smoothed
        )
        self._category = self._categorize(self._smoothed)
        self._history.append((t, self._smoothed))
        while self._history and self._history[0][0] < t - TREND_WINDOW_S:
            self._history.popleft()

    def _categorize(self, value: float) -> str:
        raw = "fuerte" if value >= self.strong else "media" if value >= self.medium else "débil"
        if self._category is None or raw == self._category:
            return raw
        # Solo cambia si el valor supera el umbral por más que la histéresis.
        h = self.hysteresis
        thresholds = {("fuerte", "media"): self.strong, ("media", "débil"): self.medium}
        for (upper, lower), threshold in thresholds.items():
            if self._category == upper and raw == lower and value > threshold - h:
                return upper
            if self._category == lower and raw == upper and value < threshold + h:
                return lower
        return raw

    def state(self) -> ProximityState:
        spread = None
        if len(self._samples) >= 4:
            q = statistics.quantiles([r for _, r in self._samples], n=4)
            spread = q[2] - q[0]
        return ProximityState(self._smoothed, spread, self._category, self._trend(spread))

    def _trend(self, spread: float | None) -> str | None:
        if len(self._history) < 5:
            return None
        span = self._history[-1][0] - self._history[0][0]
        if span < TREND_WINDOW_S / 2:
            return None
        xs = [t for t, _ in self._history]
        ys = [v for _, v in self._history]
        slope = statistics.linear_regression(xs, ys).slope
        change = slope * span
        if abs(change) <= max(spread or 0.0, self.hysteresis):
            return "estable"
        return "acercándose" if change > 0 else "alejándose"
