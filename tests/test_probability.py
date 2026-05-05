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


def sparse_history_rows():
    return [
        {"date": date(2025, 5, 5), "value": 27.0, "completeness": "C"},
        {"date": date(2024, 5, 5), "value": 26.0, "completeness": "C"},
        {"date": date(2010, 5, 5), "value": 25.0, "completeness": "C"},
        {"date": date(2009, 5, 5), "value": 24.0, "completeness": "C"},
        {"date": date(2008, 5, 5), "value": 23.0, "completeness": "C"},
        {"date": date(2007, 5, 5), "value": 22.0, "completeness": "C"},
        {"date": date(2006, 5, 5), "value": 21.0, "completeness": "C"},
        {"date": date(2005, 5, 5), "value": 20.0, "completeness": "C"},
        {"date": date(2004, 5, 5), "value": 19.0, "completeness": "C"},
        {"date": date(2003, 5, 5), "value": 18.0, "completeness": "C"},
    ]


def test_hko_only_probability_still_builds_without_open_meteo():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, history_rows(), None)

    assert result.samples
    assert result.metadata["open_meteo_available"] is False
    assert "Open-Meteo unavailable" in result.source


def test_history_is_collapsed_to_one_seasonal_value_per_year():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, history_rows(), None)

    assert result.metadata["historical_row_count"] == 10
    assert result.metadata["historical_year_count"] == 2
    assert result.metadata["historical_sample_count"] == 2
    assert len(result.samples) == 2


def test_year_based_fallback_expands_when_recent_window_has_too_few_years():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=0)
    result = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, sparse_history_rows(), None)

    assert result.metadata["historical_row_count"] == 10
    assert result.metadata["historical_year_count"] == 10
    assert result.metadata["historical_sample_count"] == 10
    assert len(result.samples) == 10


def test_no_history_uses_open_meteo_samples_when_available():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution(
        "max",
        date(2026, 5, 5),
        25.0,
        [],
        [24.8, 25.0, 25.1],
    )

    assert result.samples == [24.8, 25.0, 25.1]
    assert result.metadata["open_meteo_available"] is True
    assert result.metadata["open_meteo"]["count"] == 3
    assert "Open-Meteo ensemble only" in result.source


def test_no_history_without_open_meteo_uses_synthetic_band():
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution("max", date(2026, 5, 5), 25.0, [], None)

    assert result.samples == [23.5, 24.0, 24.5, 25.0, 25.5, 26.0, 26.5]
    assert result.metadata["open_meteo_available"] is False
    assert "synthetic uncertainty band" in result.source


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
    assert result.metadata["confidence_reason"] == "Low confidence: fewer than 10 matching HKO seasonal history years."


def test_same_day_observed_temperature_clamps_max_samples():
    today = date.today()
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution(
        "max",
        today,
        24.0,
        history_rows(),
        [24.0, 24.2, 24.4],
        observed_temperature=23.0,
    )

    assert min(result.samples) >= 23.0
    assert result.metadata["observed_constraint_applied"] is True


def test_no_history_still_applies_same_day_observed_constraint():
    today = date.today()
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution(
        "max",
        today,
        24.0,
        [],
        [21.5, 22.0, 22.4],
        observed_temperature=23.0,
    )

    assert min(result.samples) >= 23.0
    assert result.metadata["observed_constraint_applied"] is True


def test_forecast_error_proxy_reduces_far_tail_probability():
    today = date.today()
    engine = HKOMarketProbabilityEngine(years_back=5, window_days=7)
    result = engine.build_temperature_distribution("max", today, 24.0, history_rows(), [24.0, 24.1, 24.2])
    far_tail = TemperatureBucket("max", "below", "C", threshold=20)

    assert engine.probability(result.samples, far_tail) == 0.0


def test_probability_does_not_round_boundary_samples_into_integer_degree_bucket():
    engine = HKOMarketProbabilityEngine(years_back=30, window_days=7)
    history = [
        {"date": date(2025, 5, 6), "value": 29.96, "completeness": "C"},
        {"date": date(2024, 5, 6), "value": 30.04, "completeness": "C"},
        {"date": date(2023, 5, 6), "value": 29.96, "completeness": "C"},
        {"date": date(2022, 5, 6), "value": 30.04, "completeness": "C"},
        {"date": date(2021, 5, 6), "value": 29.96, "completeness": "C"},
        {"date": date(2020, 5, 6), "value": 30.04, "completeness": "C"},
        {"date": date(2019, 5, 6), "value": 29.96, "completeness": "C"},
        {"date": date(2018, 5, 6), "value": 30.04, "completeness": "C"},
        {"date": date(2017, 5, 6), "value": 29.96, "completeness": "C"},
        {"date": date(2016, 5, 6), "value": 30.04, "completeness": "C"},
    ]

    result = engine.build_temperature_distribution("max", date(2026, 5, 6), 30.0, history, None)

    assert min(result.samples) < 30.0
    assert max(result.samples) > 30.0
    assert engine.probability(
        result.samples,
        TemperatureBucket("max", "integer_degree", "C", lower=30, upper=31),
    ) == 0.5
