"""Margins tab — maintenance margin vs notional, vol, and range coverage."""
import io

import pandas as pd
import streamlit as st
import yfinance as yf

from common import _session, get_quote


# Margins from AMP: instrument -> AMP symbol (sector order, matching the board)
AMP_URL = "https://www.ampfutures.com/trading-info/margins"
AMP_SYMBOLS = {
    "ES  S&P 500": "ES", "NQ  Nasdaq": "NQ",
    "ZB  T-Bond": "ZB", "ZN  10Y Note": "ZN",
    "6E  Euro": "6E", "6J  Yen": "6J",
    "CL  Crude": "CL", "NG  Nat Gas": "NG",
    "GC  Gold": "GC", "SI  Silver": "SI", "HG  Copper": "HG",
    "ZC  Corn": "ZC", "ZW  Wheat": "ZW", "ZS  Soybean": "ZS",
    "SB  Sugar": "SB", "KC  Coffee": "KC",
}
# BTC/ETH aren't on AMP's list -> CME outright CSV by product code.
CME_URL = "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv"
CME_CODES = {"BTC  Bitcoin": "BTC", "ETH  Ether": "ETH"}

# label -> (yahoo ticker for price, notional multiplier).
# Multiplier folds in unit conversion so notional = yahoo_price * mult.
CONTRACT_SPECS = {
    "ES  S&P 500": ("ES=F", 50),      "NQ  Nasdaq": ("NQ=F", 20),
    "ZB  T-Bond": ("ZB=F", 1000),     "ZN  10Y Note": ("ZN=F", 1000),
    "6E  Euro": ("6E=F", 125000),     "6J  Yen": ("6J=F", 12500000),
    "BTC  Bitcoin": ("BTC-USD", 5),   "ETH  Ether": ("ETH-USD", 50),
    "CL  Crude": ("CL=F", 1000),      "NG  Nat Gas": ("NG=F", 10000),
    "GC  Gold": ("GC=F", 100),        "SI  Silver": ("SI=F", 5000),
    "HG  Copper": ("HG=F", 25000),
    "ZC  Corn": ("ZC=F", 50),         "ZW  Wheat": ("ZW=F", 50),
    "ZS  Soybean": ("ZS=F", 50),
    "SB  Sugar": ("SB=F", 1120),      "KC  Coffee": ("KC=F", 375),
}


def _money(x):
    try:
        return float(str(x).replace("$", "").replace(",", "").strip())
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_amp_margins() -> dict:
    """Scrape AMP's margins table by matching cell VALUES (robust to how the
    HTML headers get parsed). Returns {amp_symbol: {name, exch, maint, day}}."""
    wanted = set(AMP_SYMBOLS.values())
    exchanges = ("CME", "CBOT", "COMEX", "NYMEX", "ICE", "Eurex")
    html = _session.get(AMP_URL, timeout=25).text
    out: dict = {}
    for t in pd.read_html(io.StringIO(html)):
        for row in t.itertuples(index=False):
            cells = [str(c).strip() for c in row if str(c).strip().lower() != "nan"]
            sym = next((c for c in cells if c in wanted), None)
            if not sym or sym in out:
                continue
            monies = [m for m in (_money(c) for c in cells
                                  if str(c).strip().startswith("$")) if m is not None]
            if not monies:
                continue
            exch = next((c for c in cells if any(x in c for x in exchanges)), "")
            out[sym] = {
                "name": cells[0] if cells else "",
                "exch": exch,
                "maint": monies[0],
                "day": monies[1] if len(monies) > 1 else None,
            }
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def get_cme_margin(code: str):
    """Front-month maintenance for a product code from CME OUTRIGHT.csv."""
    df = pd.read_csv(io.StringIO(_session.get(CME_URL, timeout=25).text))
    hit = df[df["Product Code"].astype(str).str.strip().str.upper() == code.upper()]
    return _money(hit.iloc[0]["Maintenance"]) if not hit.empty else None


@st.cache_data(ttl=3600, show_spinner=False)
def get_atr(ticker: str, period: int = 14):
    """ATR(14) on daily bars, for 'days of range' margin coverage."""
    try:
        h = yf.Ticker(ticker, session=_session).history(period="2mo", interval="1d")
        if len(h) < period + 1:
            return None
        hi, lo, cl = h["High"], h["Low"], h["Close"]
        pc = cl.shift(1)
        tr = pd.concat([(hi - lo), (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_ann_vol(ticker: str, window: int = 20):
    """Annualized realized vol from the last `window` daily returns (× √252)."""
    try:
        h = yf.Ticker(ticker, session=_session).history(period="3mo", interval="1d")
        rets = h["Close"].pct_change().dropna()
        if len(rets) < window:
            return None
        return float(rets.tail(window).std() * (252 ** 0.5) * 100)
    except Exception:  # noqa: BLE001
        return None


def _notional(label):
    spec = CONTRACT_SPECS.get(label)
    if not spec:
        return None
    ticker, mult = spec
    q = get_quote(ticker)
    return q["last"] * mult if q["last"] is not None else None


def build_margins() -> pd.DataFrame:
    try:
        amp = get_amp_margins()
    except Exception as e:  # noqa: BLE001
        return pd.DataFrame([{"Instrument": "AMP ERROR", "Sym": "",
                              "Maint (USD)": str(e)[:60], "Notional (USD)": "",
                              "Margin %": "", "Source": ""}])

    def _row(label, sym, maint, source):
        notl = _notional(label)
        spec = CONTRACT_SPECS.get(label)
        margin_pct = (maint / notl * 100) if (maint and notl) else None
        days_atr = ann_vol = marg_vol = None
        if spec and maint:
            atr = get_atr(spec[0])
            drange = atr * spec[1] if atr else None
            if drange:
                days_atr = maint / drange
            ann_vol = get_ann_vol(spec[0])
            if ann_vol and margin_pct:
                marg_vol = margin_pct / ann_vol
        return {
            "Instrument": label, "Sym": sym,
            "Maint (USD)": f"{maint:,.0f}" if maint else "—",
            "Notional (USD)": f"{notl:,.0f}" if notl else "—",
            "Margin %": f"{margin_pct:.1f}%" if margin_pct else "—",
            "Ann Vol %": f"{ann_vol:.0f}%" if ann_vol else "—",
            "Marg/Vol": marg_vol if marg_vol is not None else float("nan"),
            "Days ATR": days_atr if days_atr is not None else float("nan"),
            "Source": source,
        }

    rows = []
    for label in list(AMP_SYMBOLS) + list(CME_CODES):
        if label in AMP_SYMBOLS:
            sym = AMP_SYMBOLS[label]
            r = amp.get(sym)
            rows.append(_row(label, sym, r["maint"] if r else None,
                             "AMP" if r else "AMP (missing)"))
        else:
            try:
                v = get_cme_margin(CME_CODES[label])
            except Exception:  # noqa: BLE001
                v = None
            rows.append(_row(label, CME_CODES[label], v, "CME CSV" if v else "—"))
    return pd.DataFrame(rows)


def render_margins() -> None:
    st.caption(
        "Overnight **maintenance** per contract (AMP retail, ~10% above raw CME; "
        "BTC/ETH from CME). **Marg/Vol** = margin % ÷ 20-day annualized vol; "
        "**Days ATR** = margin ÷ daily $range. Click a header to sort — lowest "
        "Marg/Vol first = thinnest cushion vs risk (margin-hike candidates)."
    )
    if st.button("Refresh", key="rm"):
        get_amp_margins.clear()
        get_cme_margin.clear()
        get_atr.clear()
        get_ann_vol.clear()
        st.rerun()
    df = build_margins().sort_values("Marg/Vol", ascending=True, na_position="last")
    st.table(
        df.style.format({"Marg/Vol": lambda v: "—" if pd.isna(v) else f"{v:.2f}",
                         "Days ATR": lambda v: "—" if pd.isna(v) else f"{v:.1f}"})
        .hide(axis="index")
    )
