from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import requests

from .models import Forecast
from .parser import CITY_COORDS, parse_market
from .probability import HKOMarketProbabilityEngine


class PolymarketClient:
    def __init__(
        self,
        gamma_base: str = "https://gamma-api.polymarket.com",
        clob_base: str = "https://clob.polymarket.com",
        timeout: int = 20,
    ) -> None:
        self.gamma_base = gamma_base.rstrip("/")
        self.clob_base = clob_base.rstrip("/")
        self.timeout = timeout

    def active_markets(self, limit: int = 150) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        response = requests.get(
            f"{self.gamma_base}/markets",
            params={"active": "true", "closed": "false", "limit": limit},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "data" in payload:
            rows.extend(payload["data"])
        elif isinstance(payload, list):
            rows.extend(payload)

        # Some weather contracts live inside event groups and may not appear near
        # the front of /markets, so also flatten a bounded /events scan.
        response = requests.get(
            f"{self.gamma_base}/events",
            params={"closed": "false", "limit": min(limit, 100)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        events = response.json()
        if isinstance(events, list):
            for event in events:
                rows.extend(event.get("markets") or [])

        page_size = min(limit, 100)
        for offset in range(0, 300, page_size):
            response = requests.get(
                f"{self.gamma_base}/events",
                params={"closed": "false", "tag_id": 84, "limit": page_size, "offset": offset},
                timeout=self.timeout,
            )
            response.raise_for_status()
            weather_events = response.json()
            if not isinstance(weather_events, list) or not weather_events:
                break
            for event in weather_events:
                rows.extend(event.get("markets") or [])

        seen: set[str] = set()
        active: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("id") or row.get("conditionId") or row.get("slug"))
            if key in seen:
                continue
            seen.add(key)
            if row.get("closed") is True or row.get("active") is False:
                continue
            active.append(row)
        return active

    def weather_markets(self, limit: int = 150):
        markets = []
        for raw in self.active_markets(limit=limit):
            market = parse_market(raw)
            if market:
                markets.append(market)
        return markets

    def order_book(self, token_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.clob_base}/book",
            params={"token_id": token_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def market_by_id(self, market_id: str):
        for raw in self.active_markets(limit=500):
            if str(raw.get("id")) == str(market_id):
                return parse_market(raw)
        return None


class HKOClient:
    def __init__(self, timeout: int = 8, open_meteo: "OpenMeteoClient | None" = None) -> None:
        self.forecast_base = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"
        self.history_base = "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php"
        self.timeout = timeout
        self.open_meteo = open_meteo or OpenMeteoClient(timeout=timeout)
        self.probability_engine = HKOMarketProbabilityEngine()
        self._forecast_cache: dict[str, Any] | None = None
        self._history_cache: dict[tuple[str, int | None], list[dict[str, Any]]] = {}

    def forecast(self, city: str, target_date: date, metric: str, unit: str = "C") -> Forecast | None:
        if city.lower() != "hong kong" or unit.upper() != "C":
            return None
        data = self._forecast_data()
        if not data:
            return None
        target_key = target_date.strftime("%Y%m%d")
        for row in data.get("weatherForecast", []):
            if row.get("forecastDate") != target_key:
                continue
            temp = row.get("forecastMaxtemp" if metric == "max" else "forecastMintemp", {})
            point = float(temp.get("value"))
            open_meteo_samples = self.open_meteo.ensemble_samples("hong kong", target_date, metric, "C")
            result = self.probability_engine.build_temperature_distribution(
                metric=metric,
                target_date=target_date,
                hko_point=point,
                history=self.historical_temperatures(metric),
                open_meteo_samples=open_meteo_samples,
            )
            return Forecast(
                city="hong kong",
                forecast_date=target_date,
                metric=metric,
                point_value=point,
                samples=result.samples,
                source=result.source,
                generated_at=datetime.now(timezone.utc),
                metadata=result.metadata,
            )
        return None

    def calibrated_samples(
        self,
        metric: str,
        target_date: date,
        point: float,
        years_back: int = 30,
        window_days: int = 7,
    ) -> list[float]:
        engine = HKOMarketProbabilityEngine(years_back=years_back, window_days=window_days)
        return engine.build_temperature_distribution(
            metric=metric,
            target_date=target_date,
            hko_point=point,
            history=self.historical_temperatures(metric),
            open_meteo_samples=None,
        ).samples

    def historical_temperatures(self, metric: str, year: int | None = None) -> list[dict[str, Any]]:
        data_type = "CLMMAXT" if metric == "max" else "CLMMINT"
        cache_key = (data_type, year)
        if cache_key in self._history_cache:
            return self._history_cache[cache_key]
        params: dict[str, Any] = {
            "dataType": data_type,
            "rformat": "json",
            "station": "HKO",
        }
        if year is not None:
            params["year"] = year
        try:
            response = requests.get(self.history_base, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            self._history_cache[cache_key] = []
            return []
        rows = []
        for year_value, month_value, day_value, value, completeness in payload.get("data", []):
            if not value:
                continue
            try:
                observed_date = date(int(year_value), int(month_value), int(day_value))
                observed_value = float(value)
            except ValueError:
                continue
            rows.append(
                {
                    "date": observed_date,
                    "value": observed_value,
                    "completeness": completeness,
                    "metric": metric,
                    "station": "HKO",
                }
            )
        self._history_cache[cache_key] = rows
        return rows

    def _forecast_data(self) -> dict[str, Any] | None:
        if self._forecast_cache is not None:
            return self._forecast_cache
        try:
            response = requests.get(
                self.forecast_base,
                params={"dataType": "fnd", "lang": "en"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            self._forecast_cache = response.json()
        except requests.RequestException:
            self._forecast_cache = None
        return self._forecast_cache


class OpenMeteoClient:
    def __init__(self, timeout: int = 8) -> None:
        self.base = "https://api.open-meteo.com/v1/forecast"
        self.ensemble_base = "https://ensemble-api.open-meteo.com/v1/ensemble"
        self.timeout = timeout
        self._cache: dict[tuple[str, str], dict[str, Any] | None] = {}
        self._ensemble_cache: dict[tuple[str, str, str], list[float] | None] = {}

    def forecast(self, city: str, target_date: date, metric: str, unit: str = "F") -> Forecast | None:
        coords = CITY_COORDS.get(city.lower())
        if not coords:
            return None
        cache_key = (city.lower(), unit.upper())
        if cache_key in self._cache:
            return self._forecast_from_daily(city, target_date, metric, unit, self._cache[cache_key])

        latitude, longitude, tz = coords
        temperature_unit = "celsius" if unit.upper() == "C" else "fahrenheit"
        try:
            response = requests.get(
                self.base,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "temperature_unit": temperature_unit,
                    "forecast_days": 16,
                    "timezone": tz,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            daily = response.json().get("daily", {})
        except requests.RequestException:
            self._cache[cache_key] = None
            return None
        self._cache[cache_key] = daily
        return self._forecast_from_daily(city, target_date, metric, unit, daily)

    def ensemble_samples(self, city: str, target_date: date, metric: str, unit: str = "C") -> list[float]:
        cache_key = (city.lower(), target_date.isoformat(), metric)
        if cache_key in self._ensemble_cache:
            return self._ensemble_cache[cache_key] or []
        samples = self._ensemble_samples(city, target_date, metric, unit)
        if not samples:
            deterministic = self.forecast(city, target_date, metric, unit)
            samples = deterministic.samples if deterministic else []
        self._ensemble_cache[cache_key] = samples
        return samples

    def _ensemble_samples(self, city: str, target_date: date, metric: str, unit: str) -> list[float]:
        coords = CITY_COORDS.get(city.lower())
        if not coords:
            return []
        latitude, longitude, tz = coords
        temperature_unit = "celsius" if unit.upper() == "C" else "fahrenheit"
        try:
            response = requests.get(
                self.ensemble_base,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "hourly": "temperature_2m",
                    "temperature_unit": temperature_unit,
                    "forecast_days": 10,
                    "timezone": tz,
                    "models": "gfs025",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            hourly = response.json().get("hourly", {})
        except requests.RequestException:
            return []
        times = hourly.get("time", [])
        indexes = [index for index, value in enumerate(times) if str(value).startswith(target_date.isoformat())]
        if not indexes:
            return []
        member_samples: list[float] = []
        for key, values in hourly.items():
            if key == "time" or not key.startswith("temperature_2m") or not isinstance(values, list):
                continue
            day_values = [values[index] for index in indexes if index < len(values) and values[index] is not None]
            if not day_values:
                continue
            member_samples.append(round(max(day_values) if metric == "max" else min(day_values), 1))
        return member_samples

    def _forecast_from_daily(
        self,
        city: str,
        target_date: date,
        metric: str,
        unit: str,
        daily: dict[str, Any] | None,
    ) -> Forecast | None:
        if not daily:
            return None
        dates = daily.get("time", [])
        values = daily.get("temperature_2m_max" if metric == "max" else "temperature_2m_min", [])
        if target_date.isoformat() not in dates:
            return None
        point = float(values[dates.index(target_date.isoformat())])
        return Forecast(
            city=city,
            forecast_date=target_date,
            metric=metric,
            point_value=point,
            samples=_synthetic_samples(point, unit),
            source=f"Open-Meteo deterministic forecast with paper-trading uncertainty band in {unit.upper()}",
            generated_at=datetime.now(timezone.utc),
        )


def _synthetic_samples(point: float, unit: str = "F") -> list[float]:
    offsets = [-2.5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 2.5] if unit.upper() == "C" else [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]
    weights = [1, 1, 2, 3, 4, 5, 4, 3, 2, 1, 1]
    samples: list[float] = []
    for offset, weight in zip(offsets, weights):
        samples.extend([point + offset] * weight)
    return samples


def _day_distance(left: date, right: date) -> int:
    left_key = date(2000, left.month, left.day).timetuple().tm_yday
    right_key = date(2000, right.month, right.day).timetuple().tm_yday
    diff = abs(left_key - right_key)
    return min(diff, 366 - diff)
