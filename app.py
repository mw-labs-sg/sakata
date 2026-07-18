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
CME_RULES = {
    "ES  (S&P 500)":   dict(codes={"ES"}),
    "ZB  (T-Bond)":    dict(codes={"17"}),
    "EC  (Euro FX)":   dict(codes={"EC"}),
    "CL  (Crude Oil)": dict(codes={"CL"}),
    "GC  (Gold)":      dict(codes={"GC"}),
    "ZC  (Corn)":      dict(codes={"C"}),
    "BTC (Bitcoin)":   dict(codes={"BTC"}),
}

# ES and CL are NOT in the bulk CSV — CME lists them on dedicated product pages.
# Read the current maintenance margin off these pages and set the numbers below
# (they change only a few times a year, announced via CME advisory notices):
#   ES: https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.margins.html
#   CL: https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.margins.html
MANUAL_MAINT = {
    "ES  (S&P 500)":   None,   # e.g. 16896  (set from the ES page above)
    "CL  (Crude Oil)": None,   # e.g. 6050   (set from the CL page above)
}
MANUAL_UPDATED = "not set"     # bump this date when you update the two above

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


def _to_month(s):
    """Parse a 'MM/YYYY' period string to a Timestamp (1st of month)."""
    try:
        m, y = str(s).strip().split("/")
        return pd.Timestamp(int(y), int(m), 1)
    except Exception:  # noqa: BLE001
        return pd.NaT


def _front_month(df: pd.DataFrame):
    """From rows sharing a product code, pick the front (nearest active) contract."""
    d = df.copy()
    d["_start"] = d["Start Period"].map(_to_month)
    d["_end"] = d["End Period"].map(_to_month)
    now = pd.Timestamp.now().normalize().replace(day=1)
    active = d[d["_end"] >= now]
    pool = active if not active.empty else d
    return pool.sort_values("_start").iloc[0]


def _pick(cme: pd.DataFrame, rule: dict):
    """CSV source: return the FRONT-MONTH row for a product code, or None."""
    codes = {c.upper() for c in rule["codes"]}
    df = cme[cme["Product Code"].astype(str).str.strip().str.upper().isin(codes)]
    return None if df.empty else _front_month(df)


def get_span2_margin(code: str, label: str):
    """
    SPAN 2 source for ES / CL (absent from OUTRIGHT.csv).
    Resolver order:
      1) scrape the dedicated CME margin page (works only if the table is in the
         static HTML — today it's JS-injected, so this usually returns None),
      2) fall back to the manually-set value so the row always shows a number.
    Returns (value, source_tag) or (None, None).
    """
    scraped = scrape_cme_margin_page(code)
    if scraped is not None:
        return scraped, "CME page"
    manual = MANUAL_MAINT.get(label)
    if manual is not None:
        return manual, f"manual ({MANUAL_UPDATED})"
    return None, None


CME_MARGIN_PAGES = {
    "ES": "https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.margins.html",
    "CL": "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.margins.html",
}


@st.cache_data(ttl=3600, show_spinner=False)
def scrape_cme_margin_page(code: str):
    """Best-effort: parse the nearest contract's maintenance margin off the page.
    Returns a float or None. Returns None when the table is JS-rendered."""
    url = CME_MARGIN_PAGES.get(code)
    if not url:
        return None
    try:
        html = _session.get(url, timeout=25).text
        tables = pd.read_html(io.StringIO(html))
    except Exception:  # noqa: BLE001  (no tables in static HTML, network, etc.)
        return None
    for t in tables:
        t.columns = [
            " ".join(map(str, c)).strip() if isinstance(c, tuple) else str(c).strip()
            for c in t.columns
        ]
        code_col = next((c for c in t.columns if "product code" in c.lower()), None)
        maint_col = next((c for c in t.columns if "maintenance" in c.lower()), None)
        if not code_col or not maint_col:
            continue
        m = t[t[code_col].astype(str).str.strip().str.upper().eq(code.upper())]
        if m.empty:
            continue
        try:
            return float(str(m.iloc[0][maint_col]).replace(",", "").replace("$", ""))
        except Exception:  # noqa: BLE001
            continue
    return None


def _fmt_maint(v) -> str:
    try:
        return f"{float(str(v).replace(',', '')):,.0f}"
    except Exception:  # noqa: BLE001
        return str(v)


SPAN2_PRODUCTS = {"ES  (S&P 500)", "CL  (Crude Oil)"}


def build_margins() -> pd.DataFrame:
    try:
        cme = get_cme_raw()
    except Exception as e:  # noqa: BLE001
        return pd.DataFrame([{"Instrument": "ERROR", "Month": "", "Code": "",
                              "Maint (USD)": str(e), "Vol Scan": "", "Source": ""}])
    rows = []
    for label, rule in CME_RULES.items():
        # 1) Legacy SPAN via OUTRIGHT.csv (front-month row)
        r = _pick(cme, rule)
        if r is not None:
            rows.append({
                "Instrument": label,
                "Month": str(r["Start Period"]).strip(),
                "Code": str(r["Product Code"]).strip(),
                "Maint (USD)": _fmt_maint(r["Maintenance"]),
                "Vol Scan": r.get("Maint. Vol. Scan", ""),
                "Source": "CME CSV",
            })
            continue
        # 2) SPAN 2 source (ES / CL): try page scrape, then manual fallback
        if label in SPAN2_PRODUCTS:
            code = next(iter(rule["codes"]))
            val, src = get_span2_margin(code, label)
            if val is not None:
                rows.append({
                    "Instrument": label, "Month": "front", "Code": code,
                    "Maint (USD)": _fmt_maint(val), "Vol Scan": "—",
                    "Source": src,
                })
            else:
                rows.append({
                    "Instrument": label, "Month": "—", "Code": code,
                    "Maint (USD)": "— set in code", "Vol Scan": "—",
                    "Source": "SPAN2 page",
                })
            continue
        # 3) Neither
        rows.append({
            "Instrument": label, "Month": "—", "Code": "—",
            "Maint (USD)": "—", "Vol Scan": "—", "Source": "not found",
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
