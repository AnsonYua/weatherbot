# Polymarket Weather Edge Scanner

Private, read-only v1 for scanning Polymarket Hong Kong Observatory temperature markets against official HKO forecasts.

This version uses no Polymarket keys, no wallet, and no live trading. It only:

- reads public Polymarket market metadata and prices
- reads public CLOB order books when needed
- reads Hong Kong Observatory 9-day forecasts
- can download HKO historical daily maximum/minimum temperatures for calibration work
- computes model probability vs market probability
- logs paper trades locally in `data/paper_trades.json`

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Safety Rules

- Do not add private keys to this project.
- Treat every signal as research, not financial advice.
- Paper trade for 2-4 weeks before risking capital.
- If live trading is added later, use a new wallet and strict manual approval.

## How The Signal Works

```text
Fetch active markets
-> keep parseable weather temperature markets
-> parse city/date/high-low/bucket
-> fetch HKO forecast
-> create an uncertainty sample band around forecast
-> model probability = samples in bucket / total samples
-> edge = model probability - market probability
-> propose paper trade only when edge/liquidity/spread pass filters
```
