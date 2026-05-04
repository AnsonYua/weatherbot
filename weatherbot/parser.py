from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from .models import Market, TemperatureBucket


CITY_COORDS: dict[str, tuple[float, float, str]] = {
    "hong kong": (22.3193, 114.1694, "Asia/Hong_Kong"),
    "nyc": (40.7128, -74.0060, "America/New_York"),
    "new york": (40.7128, -74.0060, "America/New_York"),
    "los angeles": (34.0522, -118.2437, "America/Los_Angeles"),
    "chicago": (41.8781, -87.6298, "America/Chicago"),
    "miami": (25.7617, -80.1918, "America/New_York"),
    "boston": (42.3601, -71.0589, "America/New_York"),
    "philadelphia": (39.9526, -75.1652, "America/New_York"),
    "washington dc": (38.9072, -77.0369, "America/New_York"),
    "denver": (39.7392, -104.9903, "America/Denver"),
    "san francisco": (37.7749, -122.4194, "America/Los_Angeles"),
    "seattle": (47.6062, -122.3321, "America/Los_Angeles"),
    "austin": (30.2672, -97.7431, "America/Chicago"),
    "dallas": (32.7767, -96.7970, "America/Chicago"),
    "houston": (29.7604, -95.3698, "America/Chicago"),
    "atlanta": (33.7490, -84.3880, "America/New_York"),
    "phoenix": (33.4484, -112.0740, "America/Phoenix"),
    "las vegas": (36.1699, -115.1398, "America/Los_Angeles"),
}

WEATHER_WORDS = (
    "temperature",
    "high temp",
    "low temp",
    "highest temperature",
    "lowest temperature",
)
NON_TEMPERATURE_WORDS = ("precipitation", "rainfall", "rain", "snow", "mm")


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []


def is_weather_temperature(raw: dict[str, Any]) -> bool:
    text = " ".join(
        str(raw.get(key, ""))
        for key in ("question", "title", "slug", "description", "groupItemTitle", "feeType")
    ).lower()
    if any(word in text for word in NON_TEMPERATURE_WORDS):
        return False
    return any(word in text for word in WEATHER_WORDS)


def parse_city(text: str) -> str | None:
    lowered = text.lower().replace("washington, d.c.", "washington dc")
    for city in sorted(CITY_COORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(city)}\b", lowered):
            return city
    return None


def normalize_temperature_text(text: str) -> str:
    return (
        text.lower()
        .replace("Â°", "")
        .replace("°", "")
        .replace("deg. c", "c")
        .replace("deg c", "c")
        .replace("degrees celsius", "c")
        .replace("degree celsius", "c")
        .replace("celsius", "c")
        .replace("fahrenheit", "f")
    )


def parse_metric(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(high|maximum|highest|max temp)\b", lowered):
        return "max"
    if re.search(r"\b(low|minimum|lowest|min temp)\b", lowered):
        return "min"
    return "max"


def parse_bucket(question: str, group_title: str = "") -> TemperatureBucket | None:
    text = normalize_temperature_text(f"{question} {group_title}")
    group_text = normalize_temperature_text(group_title)
    metric = parse_metric(text)
    unit = "C" if re.search(r"\d+(?:\.\d+)?\s*c\b", text) else "F"

    exact_celsius = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*c\s*", group_text)
    if exact_celsius:
        lower = float(exact_celsius.group(1))
        return TemperatureBucket(
            metric=metric,
            operator="integer_degree",
            unit="C",
            lower=lower,
            upper=lower + 1,
        )

    c_or_below = re.search(r"(-?\d+(?:\.\d+)?)\s*c\s*(?:or\s*)?(?:below|under|lower)", text)
    if c_or_below:
        return TemperatureBucket(
            metric=metric,
            operator="below",
            unit="C",
            threshold=float(c_or_below.group(1)) + 1,
        )

    c_or_higher = re.search(r"(-?\d+(?:\.\d+)?)\s*c\s*(?:or\s*)?(?:higher|above|over)", text)
    if c_or_higher:
        return TemperatureBucket(
            metric=metric,
            operator="at_or_above",
            unit="C",
            threshold=float(c_or_higher.group(1)),
        )

    between = re.search(
        r"(-?\d+(?:\.\d+)?)\s*(?:-|to|through)\s*(-?\d+(?:\.\d+)?)\s*[fc]?",
        group_text,
    )
    if between:
        return TemperatureBucket(
            metric=metric,
            operator="between",
            unit=unit,
            lower=float(between.group(1)),
            upper=float(between.group(2)),
        )

    threshold_patterns = [
        (r"(?:at least|at or above|greater than or equal to)\s*(-?\d+(?:\.\d+)?)\s*[fc]?", "at_or_above"),
        (r"(?:above|over|greater than|more than)\s*(-?\d+(?:\.\d+)?)\s*[fc]?", "above"),
        (r"(?:at most|at or below|less than or equal to)\s*(-?\d+(?:\.\d+)?)\s*[fc]?", "at_or_below"),
        (r"(?:below|under|less than)\s*(-?\d+(?:\.\d+)?)\s*[fc]?", "below"),
    ]
    for pattern, operator in threshold_patterns:
        match = re.search(pattern, text)
        if match:
            return TemperatureBucket(
                metric=metric,
                operator=operator,
                unit=unit,
                threshold=float(match.group(1)),
            )

    simple_threshold = re.search(r"(-?\d+(?:\.\d+)?)\s*[fc]", group_text)
    if simple_threshold and any(word in group_text for word in ("above", "over", "+")):
        return TemperatureBucket(metric=metric, operator="above", unit=unit, threshold=float(simple_threshold.group(1)))
    if simple_threshold and any(word in group_text for word in ("below", "under", "<")):
        return TemperatureBucket(metric=metric, operator="below", unit=unit, threshold=float(simple_threshold.group(1)))
    return None


def parse_market(raw: dict[str, Any]) -> Market | None:
    if not is_weather_temperature(raw):
        return None

    title = str(raw.get("question") or raw.get("title") or "")
    group_title = str(raw.get("groupItemTitle") or "")
    city = parse_city(f"{title} {raw.get('description', '')} {raw.get('slug', '')}")
    bucket = parse_bucket(title, group_title)
    if not city or not bucket:
        return None

    outcomes = parse_json_list(raw.get("outcomes"))
    prices = [float(price) for price in parse_json_list(raw.get("outcomePrices")) if str(price)]
    if outcomes and "Yes" in outcomes and len(prices) >= len(outcomes):
        yes_price = prices[outcomes.index("Yes")]
    elif prices:
        yes_price = prices[0]
    else:
        yes_price = float(raw.get("lastTradePrice") or 0)
    no_price = 1 - yes_price if yes_price else 0

    event_date = None
    for key in ("endDateIso", "endDate"):
        raw_date = str(raw.get(key) or "")[:10]
        try:
            event_date = date.fromisoformat(raw_date)
            break
        except ValueError:
            pass

    slug = str(raw.get("slug") or raw.get("id"))
    return Market(
        id=str(raw.get("id") or raw.get("conditionId") or slug),
        title=title,
        slug=slug,
        url=f"https://polymarket.com/market/{slug}",
        event_date=event_date,
        city=city,
        bucket=bucket,
        yes_price=yes_price,
        no_price=no_price,
        best_bid=_float_or_none(raw.get("bestBid")),
        best_ask=_float_or_none(raw.get("bestAsk")),
        spread=_float_or_none(raw.get("spread")),
        liquidity=float(raw.get("liquidityNum") or raw.get("liquidity") or 0),
        volume=float(raw.get("volumeNum") or raw.get("volume") or 0),
        token_ids=[str(token) for token in parse_json_list(raw.get("clobTokenIds"))],
        resolution_source=str(raw.get("resolutionSource") or ""),
        raw=raw,
    )


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
