from datetime import date

from weatherbot.clients import HKOClient


def test_hko_history_parses_json_payload(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [["2025", "5", "4", "25.3", "C"]]}

    def fake_get(*args, **kwargs):
        return Response()

    monkeypatch.setattr("weatherbot.clients.requests.get", fake_get)
    rows = HKOClient().historical_temperatures("max", 2025)
    assert rows == [
        {
            "date": date(2025, 5, 4),
            "value": 25.3,
            "completeness": "C",
            "metric": "max",
            "station": "HKO",
        }
    ]


def test_hko_forecast_uses_official_max_temp(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "weatherForecast": [
                    {
                        "forecastDate": "20260505",
                        "forecastMaxtemp": {"value": 25, "unit": "C"},
                        "forecastMintemp": {"value": 22, "unit": "C"},
                    }
                ]
            }

    def fake_get(*args, **kwargs):
        return Response()

    monkeypatch.setattr("weatherbot.clients.requests.get", fake_get)
    forecast = HKOClient().forecast("hong kong", date(2026, 5, 5), "max", "C")
    assert forecast is not None
    assert forecast.point_value == 25
    assert "Hong Kong Observatory" in forecast.source


def test_hko_current_temperature_parses_observatory_station(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "temperature": {
                    "data": [
                        {"place": "King's Park", "value": 22, "unit": "C"},
                        {"place": "Hong Kong Observatory", "value": 23, "unit": "C"},
                    ]
                }
            }

    def fake_get(*args, **kwargs):
        return Response()

    monkeypatch.setattr("weatherbot.clients.requests.get", fake_get)

    assert HKOClient().current_hko_temperature() == 23.0


def test_hko_calibrated_samples_shift_history_to_forecast(monkeypatch):
    client = HKOClient()
    rows = [
        {"date": date(2025, 5, 1), "value": 23.0, "completeness": "C", "metric": "max", "station": "HKO"},
        {"date": date(2025, 5, 4), "value": 25.0, "completeness": "C", "metric": "max", "station": "HKO"},
        {"date": date(2025, 5, 7), "value": 27.0, "completeness": "C", "metric": "max", "station": "HKO"},
        {"date": date(2024, 5, 4), "value": 29.0, "completeness": "P", "metric": "max", "station": "HKO"},
    ]
    monkeypatch.setattr(client, "historical_temperatures", lambda metric: rows)

    samples = client.calibrated_samples("max", date(2026, 5, 5), point=24.0, years_back=5, window_days=7)

    assert samples == [23.2, 24.0, 24.8]
