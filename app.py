from __future__ import annotations

from flask import Flask, jsonify, redirect, render_template, request, url_for

from weatherbot.clients import HKOClient, PolymarketClient
from weatherbot.signals import SignalEngine
from weatherbot.storage import PaperStore


def create_app() -> Flask:
    app = Flask(__name__)
    polymarket = PolymarketClient()
    weather = HKOClient()
    engine = SignalEngine(polymarket=polymarket, weather=weather)
    store = PaperStore("data/paper_trades.json")

    @app.get("/")
    def dashboard():
        bankroll = _positive_float(request.args.get("bankroll"), default=100.0)
        signals = engine.scan(limit=120)
        summary = store.summary()
        return render_template(
            "dashboard.html",
            signals=signals,
            summary=summary,
            bankroll=bankroll,
        )

    @app.get("/market/<market_id>")
    def market_detail(market_id: str):
        signal = engine.signal_for_market(market_id)
        if signal is None:
            return render_template("not_found.html", market_id=market_id), 404
        trades = store.for_market(market_id)
        return render_template("market.html", signal=signal, trades=trades)

    @app.post("/paper")
    def add_paper_trade():
        store.add(
            market_id=request.form["market_id"],
            title=request.form["title"],
            side=request.form["side"],
            price=float(request.form["price"]),
            size_usd=float(request.form.get("size_usd", 5)),
            model_probability=float(request.form["model_probability"]),
            edge=float(request.form["edge"]),
            notes=request.form.get("notes", "scanner proposal"),
        )
        return redirect(request.referrer or url_for("dashboard"))

    @app.get("/journal")
    def journal():
        return render_template("journal.html", trades=store.all(), summary=store.summary())

    @app.get("/api/signals")
    def api_signals():
        return jsonify([signal.to_dict() for signal in engine.scan(limit=120)])

    return app


app = create_app()


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
