"""
Sakata — Futures Board (v1)
---------------------------
Two tabs:
  • Board   — current price + day change (yfinance)
  • Margins — current CME maintenance margin per contract (CME public CSV)

Data via yfinance and CME's public margins endpoint, both fetched through a
curl_cffi chrome session to dodge bot-blocking / rate limits.
"""

import datetime as dt
import io
import time

import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cffi_requests

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Sakata", page_icon="🎋", layout="centered")

# Price board. name -> (yahoo_ticker, decimals)
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

# CME margins. name -> keyword to match in CME's "Product Name" column.
# SB (Sugar #11) is an ICE product, so it's intentionally absent here.
CME_URL = "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv"
CME_MATCH = {
    "ES  (S&P 500)":   "E-MINI S&P 500",
    "ZB  (T-Bond)":    "U.S. TREASURY BOND",
    "EC  (Euro FX)":   "EURO FX",
    "CL  (Crude Oil)": "CRUDE OIL",
    "GC  (Gold)":      "GOLD FUTURES",
    "ZC  (Corn)":      "CORN FUTURES",
    "BTC (Bitcoin)":   "BITCOIN",
}

# Shared browser-impersonating session (kept out of Streamlit's cache).
_session = cffi_requests.Session(impersonate="chrome110")


# --------------------------------------------------------------------------- #
# Data — prices
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
# Data — CME margins
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=3600, show_spinner=False)
def get_cme_raw() -> pd.DataFrame:
    """Download the full CME outright maintenance-margin CSV."""
    raw = _session.get(CME_URL, timeout=25).text
    df = pd.read_csv(io.StringIO(raw))
    df["Product Name"] = df["Product Name"].astype(str).str.upper()
    return df


def build_margins() -> pd.DataFrame:
    try:
        cme = get_cme_raw()
    except Exception as e:  # noqa: BLE001
        return pd.DataFrame([{"Instrument": "ERROR", "Maintenance": str(e),
                              "Vol Scan": "", "Matched product": ""}])
    rows = []
    for label, kw in CME_MATCH.items():
        hit = cme[cme["Product Name"].str.contains(kw, na=False)]
        if hit.empty:
            rows.append({"Instrument": label, "Maintenance": "—",
                         "Vol Scan": "—", "Matched product": "(no match)"})
        else:
            r = hit.iloc[0]
            rows.append({
                "Instrument": label,
                "Maintenance": r["Maintenance"],
                "Vol Scan": r.get("Maint. Vol. Scan", ""),
                "Matched product": str(r["Product Name"]).title(),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
def render_board() -> None:
    if st.button("🔄 Refresh prices"):
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


def render_margins() -> None:
    st.caption(
        "CME maintenance margin per contract (initial ≈ maintenance × ~1.1; "
        "your broker sets its own house margin). Sugar (SB) is ICE, not CME, so "
        "it's not shown. Updated by CME roughly daily."
    )
    if st.button("🔄 Refresh margins"):
        get_cme_raw.clear()
        st.rerun()
    st.table(build_margins().style.hide(axis="index"))


def main() -> None:
    st.title("🎋 Sakata")
    st.caption(f"Refreshed {dt.datetime.now():%Y-%m-%d %H:%M:%S}")

    tab_board, tab_margins = st.tabs(["Board", "Margins"])
    with tab_board:
        render_board()
    with tab_margins:
        render_margins()


if __name__ == "__main__":
    main()
