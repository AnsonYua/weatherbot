from datetime import date, datetime, timezone

from weatherbot.models import Forecast, Market, TemperatureBucket
from weatherbot.signals import SignalEngine


class FakePoly:
    def weather_markets(self, limit=150):
        return []

    def market_by_id(self, market_id):
        return None


class FakeWeather:
    def __init__(self, forecast):
        self._forecast = forecast

    def forecast(self, city, target_date, metric, unit="F"):
        return self._forecast


def make_market():
    return Market(
        id="1",
        title="Will NYC high temperature be above 70F?",
        slug="m",
        url="https://polymarket.com/market/m",
        event_date=date(2026, 5, 5),
        city="nyc",
        bucket=TemperatureBucket(metric="max", operator="above", threshold=70),
        yes_price=0.5,
        no_price=0.5,
        best_bid=0.49,
        best_ask=0.51,
        spread=0.02,
        liquidity=1000,
        volume=5000,
        token_ids=[],
        resolution_source="",
        raw={},
    )


def test_signal_proposes_when_edge_is_large():
    forecast = Forecast(
        city="nyc",
        forecast_date=date(2026, 5, 5),
        metric="max",
        point_value=75,
        samples=[69, 71, 72, 75, 78],
        source="test",
        generated_at=datetime.now(timezone.utc),
    )
    engine = SignalEngine(FakePoly(), FakeWeather(forecast))
    signal = engine.build_signal(make_market())
    assert signal is not None
    assert signal.action == "PROPOSE BUY YES"
    assert signal.suggested_size_usd > 0
    assert round(signal.kelly_fraction, 4) == 0.6


def test_signal_waits_when_spread_is_wide():
    forecast = Forecast(
        city="nyc",
        forecast_date=date(2026, 5, 5),
        metric="max",
        point_value=75,
        samples=[71, 72, 75, 78],
        source="test",
        generated_at=datetime.now(timezone.utc),
    )
    market = make_market()
    market = Market(**{**market.__dict__, "spread": 0.2})
    engine = SignalEngine(FakePoly(), FakeWeather(forecast))
    signal = engine.build_signal(market)
    assert signal is not None
    assert signal.action == "WAIT"


def test_signal_waits_when_both_sides_have_no_positive_edge():
    forecast = Forecast(
        city="nyc",
        forecast_date=date(2026, 5, 5),
        metric="max",
        point_value=75,
        samples=[71, 72],
        source="test",
        generated_at=datetime.now(timezone.utc),
    )
    market = make_market()
    market = Market(**{**market.__dict__, "yes_price": 0.99, "no_price": 0.01})
    engine = SignalEngine(FakePoly(), FakeWeather(forecast))
    signal = engine.build_signal(market)
    assert signal is not None
    assert signal.action == "WAIT"
    assert signal.suggested_size_usd == 0


def test_signal_uses_no_probability_for_no_side():
    forecast = Forecast(
        city="nyc",
        forecast_date=date(2026, 5, 5),
        metric="max",
        point_value=65,
        samples=[60, 61, 62, 63],
        source="test",
        generated_at=datetime.now(timezone.utc),
    )
    market = make_market()
    market = Market(**{**market.__dict__, "yes_price": 0.5, "no_price": 0.5})
    engine = SignalEngine(FakePoly(), FakeWeather(forecast))
    signal = engine.build_signal(market)
    assert signal is not None
    assert signal.side == "NO"
    assert signal.side_probability == 1.0
    assert signal.kelly_fraction == 1.0
