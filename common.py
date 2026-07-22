"""Sakata — shared core: HTTP session, instrument universe, price primitives."""
import datetime as dt
import time

import streamlit as st
import yfinance as yf
from curl_cffi import requests as cffi_requests

_session = cffi_requests.Session(impersonate="chrome110")


# Board: name -> (yahoo_ticker, decimals)
# Scanner sectors. sector -> {name: (yahoo_ticker, decimals)}
SECTORS = {
    "Indices":    {"ES  S&P 500": ("ES=F", 2), "NQ  Nasdaq": ("NQ=F", 2)},
    "Bonds":      {"ZB  T-Bond": ("ZB=F", 3), "ZN  10Y Note": ("ZN=F", 3),
                   "SR3  SOFR": ("SR3=F", 4)},
    "Currencies": {"6E  Euro": ("6E=F", 4), "6J  Yen": ("6J=F", 7)},
    "Crypto":     {"BTC  Bitcoin": ("BTC-USD", 0), "ETH  Ether": ("ETH-USD", 2)},
    "Energy":     {"CL  Crude": ("CL=F", 2), "NG  Nat Gas": ("NG=F", 3)},
    "Metals":     {"GC  Gold": ("GC=F", 1), "SI  Silver": ("SI=F", 3),
                   "HG  Copper": ("HG=F", 4)},
    "Grains":     {"ZC  Corn": ("ZC=F", 2), "ZW  Wheat": ("ZW=F", 2),
                   "ZS  Soybean": ("ZS=F", 2)},
    "Softs":      {"SB  Sugar": ("SB=F", 2), "KC  Coffee": ("KC=F", 2)},
}
SYMBOLS = {k: v for g in SECTORS.values() for k, v in g.items()}


@st.cache_data(ttl=60, show_spinner=False)
def get_quote(ticker: str, attempts: int = 3) -> dict:
    last_err = None
    for i in range(attempts):
        try:
            hist = yf.Ticker(ticker, session=_session).history(period="5d", interval="1d")
            if not hist.empty:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                chg = last - prev
                pct = (chg / prev * 100) if prev else 0.0
                return {"last": last, "chg": chg, "pct": pct}
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(0.6 * (i + 1))
    return {"last": None, "chg": None, "pct": None, "err": last_err}


@st.cache_data(ttl=300, show_spinner=False)
def get_perf(ticker: str) -> dict:
    """Last close + Day/WTD/MTD/QTD/YTD % from 1y of daily closes."""
    try:
        h = yf.Ticker(ticker, session=_session).history(period="1y", interval="1d")
        s = h["Close"].dropna()
        if s.empty:
            return {}
        pairs = [(d.date(), float(v)) for d, v in zip(s.index, s.values)]
        today, last = pairs[-1]

        def ref_before(boundary):
            r = None
            for d, v in pairs:
                if d < boundary:
                    r = v
                else:
                    break
            return r

        def pct(ref):
            return round((last / ref - 1) * 100, 2) if ref else float("nan")

        wk = today - dt.timedelta(days=today.weekday())            # Monday
        mo = today.replace(day=1)
        qt = dt.date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        yr = dt.date(today.year, 1, 1)
        day = round((last / pairs[-2][1] - 1) * 100, 2) if len(pairs) > 1 else float("nan")
        return {"last": last, "day": day, "wtd": pct(ref_before(wk)),
                "mtd": pct(ref_before(mo)), "qtd": pct(ref_before(qt)),
                "ytd": pct(ref_before(yr))}
    except Exception:  # noqa: BLE001
        return {}
