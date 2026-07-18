"""
Sakata — Futures Board (v1)
---------------------------
Small, plain dashboard: current price + day change for a fixed set of futures.
Data via yfinance, using a curl_cffi chrome session to dodge rate limits.

Keep it boring for now. Charts / levels / P&L come later.
"""

import datetime as dt
import time

import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cffi_requests

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Sakata", page_icon="🎋", layout="centered")

# Your eight. name -> (yahoo_ticker, decimals)
SYMBOLS = {
    "ES  (S&P 500)":   ("ES=F", 2),
    "ZB  (T-Bond)":    ("ZB=F", 2),
    "EC  (Euro FX)":   ("6E=F", 4),
    "CL  (Crude Oil)": ("CL=F", 2),
    "GC  (Gold)":      ("GC=F", 1),
    "ZC  (Corn)":      ("ZC=F", 2),
    "SB  (Sugar)":     ("SB=F", 2),
    "BTC (Bitcoin)":   ("BTC=F", 0),
}

# Shared browser-impersonating session (kept out of Streamlit's cache).
_session = cffi_requests.Session(impersonate="chrome110")


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=60, show_spinner=False)
def get_quote(ticker: str, attempts: int = 3) -> dict:
    """Last price + change vs previous daily close, with retry on throttle."""
    last_err = None
    for i in range(attempts):
        try:
            hist = yf.Ticker(ticker, session=_session).history(
                period="5d", interval="1d"
            )
            if not hist.empty:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                chg = last - prev
                pct = (chg / prev * 100) if prev else 0.0
                return {"last": last, "chg": chg, "pct": pct}
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        # empty or errored -> wait a moment and retry (handles cold-start throttle)
        time.sleep(0.6 * (i + 1))
    return {"last": None, "chg": None, "pct": None, "err": last_err}


def build_board() -> pd.DataFrame:
    rows = []
    for name, (ticker, dec) in SYMBOLS.items():
        q = get_quote(ticker)
        if q["last"] is None:
            rows.append({"Instrument": name, "Last": "—", "Chg": "—", "Chg %": None})
        else:
            rows.append({
                "Instrument": name,
                "Last": f"{q['last']:,.{dec}f}",
                "Chg": f"{q['chg']:+.{dec}f}",
                "Chg %": round(q["pct"], 2),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
def main() -> None:
    st.title("🎋 Sakata")
    st.caption(
        f"Futures board · delayed data · refreshed {dt.datetime.now():%H:%M:%S}"
    )

    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

    df = build_board()

    def colour(v):
        if v is None or pd.isna(v):
            return ""
        return "color: #4ade80;" if v >= 0 else "color: #f87171;"

    styled = (
        df.style
        .map(colour, subset=["Chg %"])
        .format({"Chg %": lambda v: "—" if v is None or pd.isna(v) else f"{v:+.2f}%"})
        .hide(axis="index")
    )
    st.table(styled)


if __name__ == "__main__":
    main()
