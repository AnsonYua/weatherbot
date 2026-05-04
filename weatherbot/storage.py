from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class PaperStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def for_market(self, market_id: str) -> list[dict[str, Any]]:
        return [trade for trade in self.all() if trade["market_id"] == market_id]

    def add(
        self,
        market_id: str,
        title: str,
        side: str,
        price: float,
        size_usd: float,
        model_probability: float,
        edge: float,
        notes: str,
    ) -> dict[str, Any]:
        trade = {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "paper_open",
            "market_id": market_id,
            "title": title,
            "side": side,
            "price": price,
            "size_usd": min(size_usd, 5.0),
            "shares": round(min(size_usd, 5.0) / max(price, 0.01), 4),
            "model_probability": model_probability,
            "edge": edge,
            "notes": notes,
            "result": "",
            "pnl": 0.0,
        }
        trades = self.all()
        trades.insert(0, trade)
        self.path.write_text(json.dumps(trades, indent=2), encoding="utf-8")
        return trade

    def summary(self) -> dict[str, Any]:
        trades = self.all()
        closed = [trade for trade in trades if trade.get("status") == "paper_closed"]
        pnl = sum(float(trade.get("pnl") or 0) for trade in closed)
        wins = sum(1 for trade in closed if float(trade.get("pnl") or 0) > 0)
        return {
            "open_count": sum(1 for trade in trades if trade.get("status") == "paper_open"),
            "closed_count": len(closed),
            "total_count": len(trades),
            "pnl": pnl,
            "win_rate": wins / len(closed) if closed else 0,
        }
