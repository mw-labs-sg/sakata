"""
Sakata — Futures Board
----------------------
Board tab   : current price + day change (yfinance).
Margins tab : maintenance + day-trade margin per contract.

Margin sources:
  • AMP Futures margins page — a STATIC HTML table (scrapes cleanly, covers
    ES, CL, 6E, GC, ZB, ZC, SB incl. the ones absent from CME's CSV).
  • CME OUTRIGHT.csv — used only for BTC (AMP doesn't list Bitcoin).

Everything fetched through a curl_cffi chrome session to avoid bot-blocking.
"""

import datetime as dt
import io
import time

import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cffi_requests

st.set_page_config(page_title="Sakata", page_icon="🎋", layout="centered")

# Board: name -> (yahoo_ticker, decimals)
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

# Margins from AMP: instrument -> AMP symbol
AMP_URL = "https://www.ampfutures.com/trading-info/margins"
AMP_SYMBOLS = {
    "ES  (S&P 500)":   "ES",
    "ZB  (T-Bond)":    "ZB",
    "EC  (Euro FX)":   "6E",
    "CL  (Crude Oil)": "CL",
    "GC  (Gold)":      "GC",
    "ZC  (Corn)":      "ZC",
    "SB  (Sugar)":     "SB",
}
# BTC isn't on AMP's list -> pull from CME's outright CSV by product code.
CME_URL = "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv"
CME_CODES = {"BTC (Bitcoin)": "BTC"}

_session = cffi_requests.Session(impersonate="chrome110")


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
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
# Margins — helpers
# --------------------------------------------------------------------------- #
def _money(x):
    try:
        return float(str(x).replace("$", "").replace(",", "").strip())
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_amp_table() -> pd.DataFrame:
    """Scrape AMP's static margins table into Symbol/Name/Exchange/Maint/Day."""
    html = _session.get(AMP_URL, timeout=25).text
    rows = []
    for t in pd.read_html(io.StringIO(html)):
        cols = [str(c) for c in t.columns]
        symcol = next((c for c in cols if str(c).strip().lower() == "symbol"), None)
        maintcol = next((c for c in cols if "maintenance" in str(c).lower()), None)
        daycol = next((c for c in cols if "day" in str(c).lower()), None)
        namecol = next((c for c in cols if str(c).strip().lower() == "name"), None)
        exchcol = next((c for c in cols if "exchange" in str(c).lower()), None)
        if not symcol or not maintcol:
            continue
        t.columns = cols
        for _, r in t.iterrows():
            rows.append({
                "Symbol": str(r[symcol]).strip(),
                "Name": str(r[namecol]).strip() if namecol else "",
                "Exchange": str(r[exchcol]).strip() if exchcol else "",
                "Maint": _money(r[maintcol]),
                "Day": _money(r[daycol]) if daycol else None,
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def get_cme_btc() -> float:
    """Front-month BTC maintenance from CME OUTRIGHT.csv."""
    df = pd.read_csv(io.StringIO(_session.get(CME_URL, timeout=25).text))
    hit = df[df["Product Code"].astype(str).str.strip().str.upper() == "BTC"]
    return _money(hit.iloc[0]["Maintenance"]) if not hit.empty else None


def build_margins() -> pd.DataFrame:
    try:
        amp = get_amp_table()
    except Exception as e:  # noqa: BLE001
        return pd.DataFrame([{"Instrument": "AMP ERROR", "Sym": "", "Exchange": "",
                              "Maint (USD)": str(e), "Day (USD)": "", "Source": ""}])
    rows = []
    for label in SYMBOLS:
        if label in AMP_SYMBOLS:
            sym = AMP_SYMBOLS[label]
            hit = amp[amp["Symbol"].str.upper() == sym.upper()]
            if not hit.empty:
                r = hit.iloc[0]
                rows.append({
                    "Instrument": label, "Sym": sym, "Exchange": r["Exchange"],
                    "Maint (USD)": f"{r['Maint']:,.0f}" if r["Maint"] else "—",
                    "Day (USD)": f"{r['Day']:,.0f}" if r["Day"] else "—",
                    "Source": "AMP",
                })
            else:
                rows.append({"Instrument": label, "Sym": sym, "Exchange": "—",
                             "Maint (USD)": "—", "Day (USD)": "—", "Source": "AMP (missing)"})
        elif label in CME_CODES:
            try:
                v = get_cme_btc()
            except Exception:  # noqa: BLE001
                v = None
            rows.append({"Instrument": label, "Sym": "BTC", "Exchange": "CME",
                         "Maint (USD)": f"{v:,.0f}" if v else "—",
                         "Day (USD)": "—", "Source": "CME CSV"})
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

    st.table(
        df.style.map(colour, subset=["Chg %"])
        .format({"Chg %": lambda v: "—" if v is None or pd.isna(v) else f"{v:+.2f}%"})
        .hide(axis="index")
    )


def render_margins() -> None:
    st.caption(
        "Overnight **maintenance** + AMP **day-trade** margin per contract. "
        "Maintenance is exchange-set (AMP shows the retail figure, ~10% above raw "
        "CME). BTC comes from CME's CSV. Margins change with volatility — verify "
        "before sizing a trade."
    )
    if st.button("🔄 Refresh margins"):
        get_amp_table.clear()
        get_cme_btc.clear()
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
