from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean, median
from typing import Any

from .models import TemperatureBucket


@dataclass(frozen=True)
class ProbabilityResult:
    samples: list[float]
    source: str
    metadata: dict[str, Any]


class HKOMarketProbabilityEngine:
    def __init__(self, years_back: int = 30, window_days: int = 7) -> None:
        self.years_back = years_back
        self.window_days = window_days

    def build_temperature_distribution(
        self,
        metric: str,
        target_date: date,
        hko_point: float,
        history: list[dict[str, Any]],
        open_meteo_samples: list[float] | None = None,
    ) -> ProbabilityResult:
        candidates = self._seasonal_candidates(history, target_date)
        values = [row["value"] for row in candidates]
        if not values:
            return ProbabilityResult(
                samples=[round(hko_point, 1)],
                source="Hong Kong Observatory forecast only; HKO history unavailable",
                metadata={
                    "hko_point": hko_point,
                    "historical_sample_count": 0,
                    "confidence_reason": "No HKO historical calibration rows were available.",
                    "open_meteo_available": bool(open_meteo_samples),
                },
            )

        baseline = median(values)
        historical_offsets = [value - baseline for value in values]
        om_samples = [float(value) for value in (open_meteo_samples or []) if value is not None]
        om_summary = self._open_meteo_summary(om_samples)
        disagreement = (om_summary["median"] - hko_point) if om_summary else 0.0
        center = hko_point + (disagreement * 0.25 if om_summary else 0.0)
        spread_factor = self._spread_factor(disagreement, bool(om_summary))

        samples = [round(center + offset * spread_factor, 1) for offset in historical_offsets]
        if om_samples:
            om_center = median(om_samples)
            samples.extend(round(center + (value - om_center) * 0.5, 1) for value in om_samples)

        source = "HKO 9-day forecast calibrated with HKO history"
        if om_summary:
            source += " and Open-Meteo model agreement"
        else:
            source += "; Open-Meteo unavailable"

        metadata = {
            "hko_point": hko_point,
            "metric": metric,
            "seasonal_baseline": round(baseline, 2),
            "historical_sample_count": len(values),
            "historical_years": sorted({row["date"].year for row in candidates}),
            "open_meteo_available": bool(om_summary),
            "open_meteo": om_summary,
            "disagreement_c": round(disagreement, 2) if om_summary else None,
            "center_c": round(center, 2),
            "spread_factor": round(spread_factor, 2),
            "confidence_reason": self.confidence_reason(len(values), disagreement if om_summary else None),
        }
        return ProbabilityResult(samples=samples, source=source, metadata=metadata)

    def probability(self, samples: list[float], bucket: TemperatureBucket) -> float:
        if not samples:
            return 0.0
        return sum(1 for value in samples if bucket.contains(value)) / len(samples)

    def confidence_reason(self, sample_count: int, disagreement: float | None) -> str:
        if sample_count < 10:
            return "Low confidence: fewer than 10 matching HKO seasonal history rows."
        if disagreement is None:
            return "Medium confidence: HKO history is available, but Open-Meteo comparison failed."
        abs_disagreement = abs(disagreement)
        if abs_disagreement >= 2.0:
            return "Low confidence: HKO and Open-Meteo differ by at least 2.0C."
        if abs_disagreement >= 1.0:
            return "Medium confidence: HKO and Open-Meteo differ by at least 1.0C."
        return "Higher confidence: HKO and Open-Meteo are within 1.0C."

    def _seasonal_candidates(self, history: list[dict[str, Any]], target_date: date) -> list[dict[str, Any]]:
        start_year = target_date.year - self.years_back
        candidates = [
            row
            for row in history
            if start_year <= row["date"].year < target_date.year
            and _day_distance(row["date"], target_date) <= self.window_days
            and row.get("completeness") == "C"
        ]
        if len(candidates) >= 10:
            return candidates
        return [
            row
            for row in history
            if row["date"].year < target_date.year
            and _day_distance(row["date"], target_date) <= self.window_days
            and row.get("completeness") == "C"
        ]

    def _open_meteo_summary(self, samples: list[float]) -> dict[str, float] | None:
        if not samples:
            return None
        sorted_samples = sorted(samples)
        return {
            "count": len(sorted_samples),
            "min": round(min(sorted_samples), 1),
            "max": round(max(sorted_samples), 1),
            "mean": round(mean(sorted_samples), 2),
            "median": round(median(sorted_samples), 2),
        }

    def _spread_factor(self, disagreement: float, has_open_meteo: bool) -> float:
        if not has_open_meteo:
            return 1.15
        abs_disagreement = abs(disagreement)
        if abs_disagreement < 0.5:
            return 0.85
        return min(1.8, 1.0 + abs_disagreement / 3.0)


def _day_distance(left: date, right: date) -> int:
    left_key = date(2000, left.month, left.day).timetuple().tm_yday
    right_key = date(2000, right.month, right.day).timetuple().tm_yday
    diff = abs(left_key - right_key)
    return min(diff, 366 - diff)
