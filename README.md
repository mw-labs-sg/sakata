# Sakata

Small futures board (Streamlit). Current price + day change for ES, ZB, EC, CL, GC, ZC, SB, BTC.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501.

## Symbols (Yahoo tickers)

| Code | Instrument       | Ticker |
|------|------------------|--------|
| ES   | E-mini S&P 500   | ES=F   |
| ZB   | 30Y T-Bond       | ZB=F   |
| EC   | Euro FX          | 6E=F   |
| CL   | WTI Crude        | CL=F   |
| GC   | Gold             | GC=F   |
| ZC   | Corn             | ZC=F   |
| SB   | Sugar #11        | SB=F   |
| BTC  | CME Bitcoin      | BTC=F  |

## Next

Charts · level triggers · position P&L · IBKR live feed.
