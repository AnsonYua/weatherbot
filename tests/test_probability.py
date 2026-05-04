from datetime import date

from weatherbot.models import TemperatureBucket
from weatherbot.probability import HKOMarketProbabilityEngine


def history_rows():
    return [
        {"date": date(2025, 5, 1), "value": 23.0, "completeness": "C"},
        {"date": date(2025, 5, 2), "value": 24.0, "completeness": "C"},
        {"date": date(2025, 5, 3), "value": 25.0, "completeness": "C"},
        {"date": date(2025, 5, 4), "value": 26.0, "completeness": "C"},
        {"date": date(2025, 5, 5), "value": 27.0, "completeness": "C"},
        {"date": date(2024, 5, 1), "value": 23.5, "completeness": "C"},
        {"date": date(2024, 5, 2), "value": 24.5, "completeness": "C"},
        {"date": date(2024, 5, 3), "value": 25.5, "completeness": "C"},
        {"date": date(2024, 5, 4), "value": 26.5, "completeness": "C"},
        {"date": date(2024, 5, 5), "value": 27.5, "completeness": "C"},
    ]


def test_hko_only_probability_still_builds_without_open_meteo():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, history_rows(), None)

    assert result.samples
    assert result.metadata["open_meteo_available"] is False
    assert "Open-Meteo unavailable" in result.source


def test_bucket_probability_operators():
    engine = HKOMarketProbabilityEngine()
    samples = [21.0, 22.0, 23.0, 24.0]

    assert engine.probability(samples, TemperatureBucket("min", "integer_degree", "C", lower=22, upper=23)) == 0.25
    assert engine.probability(samples, TemperatureBucket("min", "above", "C", threshold=22)) == 0.5
    assert engine.probability(samples, TemperatureBucket("min", "at_or_above", "C", threshold=22)) == 0.75
    assert engine.probability(samples, TemperatureBucket("min", "below", "C", threshold=23)) == 0.5
    assert engine.probability(samples, TemperatureBucket("min", "between", "C", lower=22, upper=24)) == 0.75


def test_strong_disagreement_widens_distribution_and_lowers_confidence():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    agreed = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, history_rows(), [25.1, 25.2, 24.9])
    disagreed = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, history_rows(), [28.0, 28.2, 28.4])

    assert disagreed.metadata["spread_factor"] > agreed.metadata["spread_factor"]
    assert disagreed.metadata["confidence_reason"].startswith("Low confidence")


def test_strong_agreement_tightens_distribution():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, history_rows(), [24.8, 25.0, 25.1])

    assert result.metadata["spread_factor"] == 0.85
    assert result.metadata["confidence_reason"].startswith("Higher confidence")
