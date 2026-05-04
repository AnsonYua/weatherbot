from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class TemperatureBucket:
    metric: str
    operator: str
    unit: str = "F"
    threshold: float | None = None
    lower: float | None = None
    upper: float | None = None

    def contains(self, value: float) -> bool:
        if self.operator == "above":
            return self.threshold is not None and value > self.threshold
        if self.operator == "at_or_above":
            return self.threshold is not None and value >= self.threshold
        if self.operator == "below":
            return self.threshold is not None and value < self.threshold
        if self.operator == "at_or_below":
            return self.threshold is not None and value <= self.threshold
        if self.operator == "between":
            return (
                self.lower is not None
                and self.upper is not None
                and self.lower <= value <= self.upper
            )
        if self.operator == "integer_degree":
            return (
                self.lower is not None
                and self.upper is not None
                and self.lower <= value < self.upper
            )
        return False

    @property
    def label(self) -> str:
        unit = self.unit
        if self.operator == "between":
            return f"{self.lower:g}-{self.upper:g}{unit} {self.metric}"
        if self.operator == "integer_degree":
            return f"{self.lower:g}{unit} {self.metric}"
        return f"{self.operator.replace('_', ' ')} {self.threshold:g}{unit} {self.metric}"


@dataclass(frozen=True)
class Market:
    id: str
    title: str
    slug: str
    url: str
    event_date: date | None
    city: str
    bucket: TemperatureBucket
    yes_price: float
    no_price: float
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    liquidity: float
    volume: float
    token_ids: list[str]
    resolution_source: str
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class Forecast:
    city: str
    forecast_date: date
    metric: str
    point_value: float
    samples: list[float]
    source: str
    generated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def probability(self, bucket: TemperatureBucket) -> float:
        if not self.samples:
            return 0.0
        hits = sum(1 for value in self.samples if bucket.contains(value))
        return hits / len(self.samples)


@dataclass(frozen=True)
class Signal:
    market: Market
    forecast: Forecast | None
    side: str
    model_probability: float
    side_probability: float
    market_probability: float
    edge: float
    kelly_fraction: float
    confidence: str
    suggested_size_usd: float
    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["market"]["raw"] = {}
        if self.market.event_date:
            data["market"]["event_date"] = self.market.event_date.isoformat()
        if self.forecast:
            data["forecast"]["forecast_date"] = self.forecast.forecast_date.isoformat()
            data["forecast"]["generated_at"] = self.forecast.generated_at.isoformat()
        return data
