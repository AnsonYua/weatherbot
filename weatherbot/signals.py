from __future__ import annotations

from datetime import date

from .clients import HKOClient, PolymarketClient
from .models import Market, Signal


class SignalEngine:
    def __init__(
        self,
        polymarket: PolymarketClient,
        weather: HKOClient,
        min_edge: float = 0.08,
        max_spread: float = 0.08,
        min_liquidity: float = 100.0,
        max_size_usd: float = 5.0,
    ) -> None:
        self.polymarket = polymarket
        self.weather = weather
        self.min_edge = min_edge
        self.max_spread = max_spread
        self.min_liquidity = min_liquidity
        self.max_size_usd = max_size_usd

    def scan(self, limit: int = 150) -> list[Signal]:
        today = self.weather.local_today("hong kong")
        markets = [
            market
            for market in self.polymarket.weather_markets(limit=limit)
            if market.event_date is not None and market.event_date >= today
            and market.city == "hong kong"
            and market.bucket.unit == "C"
        ]
        signals = [self.build_signal(market) for market in markets]
        return sorted([signal for signal in signals if signal], key=lambda item: item.edge, reverse=True)[:limit]

    def signal_for_market(self, market_id: str) -> Signal | None:
        market = self.polymarket.market_by_id(market_id)
        return self.build_signal(market) if market else None

    def build_signal(self, market: Market) -> Signal | None:
        if not market.event_date:
            return None
        forecast = self.weather.forecast(market.city, market.event_date, market.bucket.metric, market.bucket.unit)
        if forecast is None:
            return Signal(
                market=market,
                forecast=None,
                side="WAIT",
                model_probability=0.0,
                side_probability=0.0,
                market_probability=market.yes_price,
                edge=0.0,
                kelly_fraction=0.0,
                confidence="low",
                suggested_size_usd=0.0,
                action="WAIT",
                reason="No matching HKO forecast date yet.",
            )

        model_probability = forecast.probability(market.bucket)
        yes_edge = model_probability - market.yes_price
        no_edge = (1 - model_probability) - market.no_price
        if yes_edge >= no_edge:
            side = "YES"
            side_probability = model_probability
            market_probability = market.yes_price
            edge = yes_edge
        else:
            side = "NO"
            side_probability = 1 - model_probability
            market_probability = market.no_price
            edge = no_edge
        kelly_fraction = self._kelly_fraction(side_probability, market_probability)

        blockers = []
        if edge < self.min_edge:
            blockers.append(f"edge below {self.min_edge:.0%}")
        if market.spread is not None and market.spread > self.max_spread:
            blockers.append(f"spread above {self.max_spread:.0%}")
        if market.liquidity < self.min_liquidity:
            blockers.append(f"liquidity below ${self.min_liquidity:.0f}")
        if market_probability < 0.01 and side_probability < 0.15:
            blockers.append("lottery tail below 1% needs at least 15% model probability")

        if blockers:
            action = "WAIT"
            suggested_size = 0.0
            reason = "; ".join(blockers)
        else:
            action = f"PROPOSE BUY {side}"
            suggested_size = self._size_for_edge(edge)
            reason = f"{side} model {side_probability:.1%} vs market {market_probability:.1%}"

        return Signal(
            market=market,
            forecast=forecast,
            side=side,
            model_probability=model_probability,
            side_probability=side_probability,
            market_probability=market_probability,
            edge=edge,
            kelly_fraction=kelly_fraction,
            confidence=self._confidence(abs(edge), market.spread, market.liquidity, forecast.metadata),
            suggested_size_usd=suggested_size,
            action=action,
            reason=reason,
        )

    def _size_for_edge(self, edge: float) -> float:
        if edge >= 0.20:
            return self.max_size_usd
        if edge >= 0.12:
            return round(self.max_size_usd * 0.7, 2)
        return round(self.max_size_usd * 0.5, 2)

    def _kelly_fraction(self, probability: float, price: float) -> float:
        if price <= 0 or price >= 1:
            return 0.0
        fraction = (probability - price) / (1 - price)
        return max(0.0, min(1.0, fraction))

    def _confidence(
        self,
        edge: float,
        spread: float | None,
        liquidity: float,
        forecast_metadata: dict | None = None,
    ) -> str:
        confidence_reason = (forecast_metadata or {}).get("confidence_reason", "")
        if str(confidence_reason).startswith("Low confidence"):
            return "low"
        if edge >= 0.15 and (spread is None or spread <= 0.04) and liquidity >= 500:
            return "high"
        if edge >= 0.08 and (spread is None or spread <= 0.08) and liquidity >= 100:
            return "medium"
        return "low"
