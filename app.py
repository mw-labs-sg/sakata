"""
Sakata — Futures Board (v1)
---------------------------
Two tabs:
  • Board   — current price + day change (yfinance)
  • Margins — current CME maintenance margin per contract (CME public CSV)

Data fetched through a curl_cffi chrome session to dodge bot-blocking.
"""

import datetime as dt
import io
import time

import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cffi_requests

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

# CME margin match rules.
#   inc   = keyword that must appear in CME "Product Name"
#   exc   = keywords that must NOT appear (kills micro/mini/strip/synthetic/BTIC)
#   exact = preferred exact product name if present
# SB (Sugar #11) is ICE, not CME, so it's not here.
CME_URL = "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv"
# Locked to exact CME Product Codes (confirmed from the outrights file).
# ES / CL may be absent from filtered exports; they resolve from the full file.
CME_RULES = {
    "ES  (S&P 500)":   dict(codes={"ES"}),
    "ZB  (T-Bond)":    dict(codes={"17"}),
    "EC  (Euro FX)":   dict(codes={"EC"}),
    "CL  (Crude Oil)": dict(codes={"CL"}),
    "GC  (Gold)":      dict(codes={"GC"}),
    "ZC  (Corn)":      dict(codes={"C"}),
    "BTC (Bitcoin)":   dict(codes={"BTC"}),
}

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
# CME margins
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=3600, show_spinner=False)
def get_cme_raw() -> pd.DataFrame:
    raw = _session.get(CME_URL, timeout=25).text
    df = pd.read_csv(io.StringIO(raw))
    df["Product Name"] = df["Product Name"].astype(str).str.upper().str.strip()
    return df


def _pick(cme: pd.DataFrame, rule: dict):
    if "codes" in rule:
        codes = {c.upper() for c in rule["codes"]}
        df = cme[cme["Product Code"].astype(str).str.strip().str.upper().isin(codes)]
        return None if df.empty else df.iloc[0]
    df = cme[cme["Product Name"].str.contains(rule["inc"], na=False)]
    for x in rule.get("exc", []):
        df = df[~df["Product Name"].str.contains(x, na=False)]
    return None if df.empty else df.iloc[0]


def _fmt_maint(v) -> str:
    try:
        return f"{float(str(v).replace(',', '')):,.0f}"
    except Exception:  # noqa: BLE001
        return str(v)


def build_margins() -> pd.DataFrame:
    try:
        cme = get_cme_raw()
    except Exception as e:  # noqa: BLE001
        return pd.DataFrame([{"Instrument": "ERROR", "Maint (USD)": str(e),
                              "Vol Scan": "", "Matched product": ""}])
    rows = []
    for label, rule in CME_RULES.items():
        r = _pick(cme, rule)
        if r is None:
            rows.append({"Instrument": label, "Code": "—", "Maint (USD)": "—",
                         "Vol Scan": "—", "Matched product": "(no match)"})
        else:
            rows.append({
                "Instrument": label,
                "Code": str(r["Product Code"]).strip(),
                "Maint (USD)": _fmt_maint(r["Maintenance"]),
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
        "CME maintenance margin per contract. Vol Scan = margin as a % of the "
        "contract's notional (a leverage/riskiness gauge). Initial ≈ maintenance "
        "× ~1.1; your broker adds house margin. Sugar (SB) is ICE, not CME."
    )
    if st.button("🔄 Refresh margins"):
        get_cme_raw.clear()
        st.rerun()
    st.table(build_margins().style.hide(axis="index"))

    with st.expander("🔍 Look up a CME product name"):
        st.caption("Type part of a contract name to see what CME calls it "
                   "(use this to fix any '(no match)' or wrong row).")
        q = st.text_input("Search", value="S&P")
        if q:
            try:
                cme = get_cme_raw()
                hit = cme[cme["Product Name"].str.contains(q.upper(), na=False)]
                st.dataframe(
                    hit[["Product Name", "Product Code", "Maintenance",
                         "Maint. Vol. Scan"]].reset_index(drop=True),
                    use_container_width=True,
                )
            except Exception as e:  # noqa: BLE001
                st.error(str(e))


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
