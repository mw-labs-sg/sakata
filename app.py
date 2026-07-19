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
import calendar
import time

import altair as alt
import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cffi_requests

st.set_page_config(page_title="Sakata", page_icon="🎋", layout="centered")

# Board: name -> (yahoo_ticker, decimals)
# Scanner sectors. sector -> {name: (yahoo_ticker, decimals)}
SECTORS = {
    "Indices":    {"ES  S&P 500": ("ES=F", 2), "NQ  Nasdaq": ("NQ=F", 2)},
    "Volatility": {"VIX  Vol": ("^VIX", 2)},
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
# BTC isn't on AMP's list -> pull from CME's outright CSV by product code.
CME_URL = "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv"
CME_CODES = {"BTC  Bitcoin": "BTC"}

# label -> (yahoo ticker for price, notional multiplier).
# Multiplier folds in unit conversion so notional = yahoo_price * mult.
CONTRACT_SPECS = {
    "ES  S&P 500": ("ES=F", 50),      "NQ  Nasdaq": ("NQ=F", 20),
    "ZB  T-Bond": ("ZB=F", 1000),     "ZN  10Y Note": ("ZN=F", 1000),
    "6E  Euro": ("6E=F", 125000),     "6J  Yen": ("6J=F", 12500000),
    "CL  Crude": ("CL=F", 1000),      "NG  Nat Gas": ("NG=F", 10000),
    "GC  Gold": ("GC=F", 100),        "SI  Silver": ("SI=F", 5000),
    "HG  Copper": ("HG=F", 25000),
    "ZC  Corn": ("ZC=F", 50),         "ZW  Wheat": ("ZW=F", 50),
    "ZS  Soybean": ("ZS=F", 50),
    "SB  Sugar": ("SB=F", 1120),      "KC  Coffee": ("KC=F", 375),
    "BTC  Bitcoin": ("BTC-USD", 5),
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


def build_scanner() -> pd.DataFrame:
    rows = []
    for sector, members in SECTORS.items():
        for name, (ticker, dec) in members.items():
            q = get_quote(ticker)
            last = None if q["last"] is None else f"{q['last']:,.{dec}f}"
            chg = None if q["chg"] is None else f"{q['chg']:+.{dec}f}"
            pct = float("nan") if q["pct"] is None else round(q["pct"], 2)
            rows.append({"Instrument": name.strip(), "Sector": sector,
                         "Last": last or "—", "Chg": chg or "—", "Chg %": pct})
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
def get_cme_btc() -> float:
    """Front-month BTC maintenance from CME OUTRIGHT.csv."""
    df = pd.read_csv(io.StringIO(_session.get(CME_URL, timeout=25).text))
    hit = df[df["Product Code"].astype(str).str.strip().str.upper() == "BTC"]
    return _money(hit.iloc[0]["Maintenance"]) if not hit.empty else None


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
        return {
            "Instrument": label, "Sym": sym,
            "Maint (USD)": f"{maint:,.0f}" if maint else "—",
            "Notional (USD)": f"{notl:,.0f}" if notl else "—",
            "Margin %": f"{maint / notl * 100:.1f}%" if (maint and notl) else "—",
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
                v = get_cme_btc()
            except Exception:  # noqa: BLE001
                v = None
            rows.append(_row(label, CME_CODES[label], v, "CME CSV"))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Economic events
# --------------------------------------------------------------------------- #
import datetime as _d


def _next_weekday(wd: int) -> _d.date:
    """Next date (today or later) falling on weekday wd (Mon=0 .. Sun=6)."""
    t = _d.date.today()
    return t + _d.timedelta(days=(wd - t.weekday()) % 7)


def _first_friday(y: int, m: int) -> _d.date:
    d = _d.date(y, m, 1)
    return d + _d.timedelta(days=(4 - d.weekday()) % 7)


def _next_first_friday() -> _d.date:
    t = _d.date.today()
    ff = _first_friday(t.year, t.month)
    if ff < t:
        y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
        ff = _first_friday(y, m)
    return ff


def _next_from_list(dates: list) -> _d.date | None:
    t = _d.date.today()
    upcoming = [d for d in dates if d >= t]
    return min(upcoming) if upcoming else None


def _last_business_day(y: int, m: int) -> _d.date:
    last = calendar.monthrange(y, m)[1]
    d = _d.date(y, m, last)
    while d.weekday() > 4:
        d -= _d.timedelta(days=1)
    return d


def _next_month_day(day: int) -> _d.date:
    """Next occurrence of the given day-of-month (today or future)."""
    t = _d.date.today()
    cand = _d.date(t.year, t.month, min(day, calendar.monthrange(t.year, t.month)[1]))
    if cand < t:
        y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
        cand = _d.date(y, m, min(day, calendar.monthrange(y, m)[1]))
    return cand


# Confirmed 2026 fixed dates
FOMC_2026 = [_d.date(2026, 7, 29), _d.date(2026, 9, 16),
             _d.date(2026, 10, 28), _d.date(2026, 12, 9)]
CPI_2026 = [_d.date(2026, 8, 12), _d.date(2026, 9, 11),   # confirmed
            _d.date(2026, 10, 13), _d.date(2026, 11, 12), _d.date(2026, 12, 10)]  # ≈

# name, next-date callable, time (ET), impact, affected instruments, exact?
EVENTS = [
    ("EIA Petroleum Status", lambda: _next_weekday(2), "10:30", "High", ["CL"], True),
    ("EIA Nat Gas Storage",  lambda: _next_weekday(3), "10:30", "High", ["NG"], True),
    ("API Crude (private)",  lambda: _next_weekday(1), "16:30", "Med",  ["CL"], True),
    ("Nonfarm Payrolls",     _next_first_friday,       "08:30", "High", ["ES", "NQ", "GC", "SI", "6E", "6J"], True),
    ("Jobless Claims",       lambda: _next_weekday(3), "08:30", "Med",  ["ES", "NQ"], True),
    ("FOMC Rate Decision",   lambda: _next_from_list(FOMC_2026), "14:00", "High", ["ES", "NQ", "GC", "SI", "HG", "6E", "6J"], True),
    ("CPI Inflation",        lambda: _next_from_list(CPI_2026),  "08:30", "High", ["ES", "NQ", "GC", "SI", "6E", "6J"], True),
    ("PCE Inflation",        lambda: _last_business_day(_d.date.today().year, _d.date.today().month), "08:30", "High", ["ES", "NQ", "GC", "SI"], False),
    ("USDA WASDE",           lambda: _next_month_day(12), "12:00", "High", ["ZC", "ZS"], False),
    ("USDA Crop Progress",   lambda: _next_weekday(0), "16:00", "Med",  ["ZC", "ZS"], False),
    ("USDA Export Sales",    lambda: _next_weekday(3), "08:30", "Med",  ["ZC", "ZS"], True),
]

INSTRUMENTS = ["ES", "NQ", "GC", "SI", "HG", "CL", "NG", "ZC", "ZS", "6E", "6J"]


# --------------------------------------------------------------------------- #
# Term structure (CME settlements)
# --------------------------------------------------------------------------- #
CURVE_URL = "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/{pid}/FUT"
# Confident productIds first; CL & NG lead the dropdown.
CURVE_PRODUCTS = {
    # CONFIRMED correct productIds (verified returning real data)
    "ES  S&P 500": 133,
    "CL  Crude":   425,
    "NG  Nat Gas": 444,
    "GC  Gold":    437,
    "SI  Silver":  458,
    "HG  Copper":  438,
    "ZC  Corn":    300,
    "ZW  Wheat":   323,
    "ZS  Soybean": 320,
    "NQ  Nasdaq":  146,
    # ZB, ZN, 6E, 6J, BTC, ETH: productIds still needed (View Source / Network)
}

# ICE products — CME's endpoint doesn't carry ICE softs. Sugar marketId from URL.
ICE_URL = ("https://www.ice.com/marketdata/DelayedMarkets.shtml"
           "?getContractsAsJson=&marketId={mid}")
# Softs (SB/KC) removed from Curve: ICE returns non-JSON and Barchart 403s
# datacenter IPs. They remain on the Board via yfinance front-month.
ICE_PRODUCTS = {}
ALL_CURVE = list(CURVE_PRODUCTS) + list(ICE_PRODUCTS)


def _num(x):
    try:
        v = float(str(x).replace(",", "").replace("+", "").strip())
        return v
    except Exception:  # noqa: BLE001
        return None


def _find_settlements(data):
    """Locate the list-of-dicts holding the monthly rows, wherever it sits."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        s = data.get("settlements")
        if isinstance(s, list):
            return [x for x in s if isinstance(x, dict)]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if any(k in v[0] for k in ("month", "settle", "last")):
                    return v
    return []


def _parse_settlements(data) -> list:
    rows = []
    for s in _find_settlements(data):
        month = str(s.get("month", "")).strip()
        if not month or month.lower() in ("total", "totals"):
            continue
        price = next((p for p in (_num(s.get("settle")), _num(s.get("last")),
                                  _num(s.get("priorSettle"))) if p is not None), None)
        if price is None:
            continue
        rows.append({
            "Month": month, "Settle": price, "Change": s.get("change", ""),
            "Volume": s.get("volume", ""), "OI": s.get("openInterest", ""),
        })
    return rows


_CME_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ("https://www.cmegroup.com/markets/energy/crude-oil/"
                "light-sweet-crude.settlements.html"),
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def _fetch_settlements(pid: int, trade_date: str) -> str:
    url = CURVE_URL.format(pid=pid) + f"?tradeDate={trade_date}"
    return _session.get(url, timeout=25, headers=_CME_HEADERS).text


def _recent_business_days(n: int = 6) -> list:
    days, d = [], _d.date.today()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= _d.timedelta(days=1)
    return days


_DATE_FMTS = ["%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"]


@st.cache_data(ttl=1800, show_spinner=False)
def _resolve_tradedate() -> str | None:
    """Find one tradeDate string that returns data (probed on CL=425)."""
    import json as _json
    for day in _recent_business_days(5):
        for fmt in _DATE_FMTS:
            ds = day.strftime(fmt)
            try:
                rows = _parse_settlements(_json.loads(_fetch_settlements(425, ds)))
                if rows:
                    return ds
            except Exception:  # noqa: BLE001
                continue
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def get_curve(pid: int) -> pd.DataFrame:
    """One request per product using the pre-resolved trade date."""
    import json as _json
    ds = _resolve_tradedate()
    if not ds:
        return pd.DataFrame()
    try:
        return pd.DataFrame(_parse_settlements(_json.loads(_fetch_settlements(pid, ds))))
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def get_curve_raw(pid: int) -> str:
    """Raw response for debug (uses resolved date, else most recent day)."""
    ds = _resolve_tradedate() or _recent_business_days(1)[0].strftime("%m/%d/%Y")
    return _fetch_settlements(pid, ds)


def build_events(selected: list) -> pd.DataFrame:
    t = _d.date.today()
    rows = []
    for name, fn, time_et, impact, insts, exact in EVENTS:
        if selected and not (set(insts) & set(selected)):
            continue
        try:
            d = fn()
        except Exception:  # noqa: BLE001
            d = None
        if d is None:
            continue
        days = (d - t).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days}d"
        rows.append({
            "_sort": d,
            "Date": ("≈ " if not exact else "") + d.strftime("%a %d %b"),
            "Time ET": time_et,
            "Event": name,
            "Impact": impact,
            "Affects": " ".join(insts),
            "Countdown": when,
        })
    df = pd.DataFrame(rows).sort_values("_sort")
    return df.drop(columns="_sort") if not df.empty else df



def render_board() -> None:
    if st.button("🔄 Refresh prices"):
        st.cache_data.clear()
        st.rerun()

    df = build_scanner()

    def pct_colour(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "color:#9ca3af;"
        return "color:#16a34a;font-weight:600;" if v >= 0 else "color:#dc2626;font-weight:600;"

    def chg_colour(s):
        s = str(s)
        if s.startswith("-"):
            return "color:#dc2626;"
        if s.startswith("+"):
            return "color:#16a34a;"
        return "color:#9ca3af;"

    def fmt_pct(v):
        return "—" if v is None or pd.isna(v) else f"{v:+.2f}%"

    # --- sector performance aggregate (top) ---
    agg = (df.dropna(subset=["Chg %"]).groupby("Sector", sort=False)["Chg %"]
           .mean().reset_index().sort_values("Chg %", ascending=False))
    agg.columns = ["Sector", "Avg %"]
    st.markdown("##### Sector performance")
    st.dataframe(
        agg.style.map(pct_colour, subset=["Avg %"]).format({"Avg %": fmt_pct}),
        hide_index=True, use_container_width=True,
        column_config={"Sector": st.column_config.TextColumn(width="medium"),
                       "Avg %": st.column_config.TextColumn(width="small")},
    )

    # --- full scanner (bottom) ---
    st.markdown("##### Scanner")
    st.dataframe(
        df.style.map(pct_colour, subset=["Chg %"])
        .map(chg_colour, subset=["Chg"]).format({"Chg %": fmt_pct}),
        hide_index=True, use_container_width=True, height=770,
        column_config={
            "Instrument": st.column_config.TextColumn(width="medium"),
            "Sector": st.column_config.TextColumn(width="small"),
            "Last": st.column_config.TextColumn(width="small"),
            "Chg": st.column_config.TextColumn(width="small"),
            "Chg %": st.column_config.TextColumn(width="small"),
        },
    )


def render_margins() -> None:
    st.caption(
        "Overnight **maintenance** + AMP **day-trade** margin per contract. "
        "Maintenance is exchange-set (AMP shows the retail figure, ~10% above raw "
        "CME). BTC comes from CME's CSV. Margins change with volatility — verify "
        "before sizing a trade."
    )
    if st.button("🔄 Refresh margins"):
        get_amp_margins.clear()
        get_cme_btc.clear()
        st.rerun()
    st.table(build_margins().style.hide(axis="index"))


def render_events() -> None:
    st.caption(
        "Next scheduled catalyst per contract. ✓ dates are rule-based or "
        "confirmed (auto-rolling); **≈** dates are estimates — verify before "
        "trading. Euro/Yen also move on ECB/BOJ decisions (check their calendars)."
    )
    sel = st.multiselect("Filter by instrument", INSTRUMENTS, default=[])
    df = build_events(sel)
    if df.empty:
        st.info("No upcoming events for that selection.")
    else:
        st.table(df.style.hide(axis="index"))


_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def _month_to_date(m: str):
    try:
        a, b = str(m).split()
        return _d.date(2000 + int(b), _MONTHS[a[:3].upper()], 1)
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def get_ice_raw(mid: int) -> str:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.ice.com/products",
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    return _session.get(ICE_URL.format(mid=mid), timeout=25, headers=headers).text


def _norm_ice_month(s: str) -> str:
    """ICE 'Oct26' / "Oct '26" -> 'OCT 26' to match CME month format."""
    import re
    m = re.match(r"\s*([A-Za-z]{3})[A-Za-z]*\s*'?(\d{2,4})", str(s))
    return f"{m.group(1).upper()} {m.group(2)[-2:]}" if m else ""


@st.cache_data(ttl=1800, show_spinner=False)
def get_ice_curve(mid: int) -> pd.DataFrame:
    import json as _json
    try:
        data = _json.loads(get_ice_raw(mid))
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    if isinstance(data, list):
        contracts = data
    elif isinstance(data, dict):
        contracts = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        contracts = []
    rows = []
    for c in contracts:
        if not isinstance(c, dict):
            continue
        strip = c.get("marketStrip") or c.get("MarketStrip") or c.get("hubName") or ""
        month = _norm_ice_month(strip)
        settle = next((p for p in (_num(c.get("settlementPrice")),
                                   _num(c.get("lastPrice")),
                                   _num(c.get("previousDaySettlementPrice")))
                       if p is not None), None)
        if not month or settle is None:
            continue
        rows.append({"Month": month, "Settle": settle,
                     "Change": c.get("change", ""), "Volume": c.get("volume", ""),
                     "OI": c.get("openInterest", "")})
    return pd.DataFrame(rows)


@st.cache_data(ttl=600, show_spinner=False)
def _load_snapshot() -> dict:
    """Read data/curves.json committed by the GitHub Action, if present."""
    import json as _json
    import os
    try:
        with open(os.path.join("data", "curves.json")) as f:
            return _json.load(f).get("curves", {})
    except Exception:  # noqa: BLE001
        return {}


def get_curve_for(name: str) -> pd.DataFrame:
    snap = _load_snapshot()
    if name in snap and snap[name]:
        return pd.DataFrame(snap[name])
    if name in CURVE_PRODUCTS:
        return get_curve(CURVE_PRODUCTS[name])
    if name in ICE_PRODUCTS:
        return get_ice_curve(ICE_PRODUCTS[name])
    return pd.DataFrame()


def get_curve_raw_for(name: str) -> str:
    if name in CURVE_PRODUCTS:
        return get_curve_raw(CURVE_PRODUCTS[name])
    return get_ice_raw(ICE_PRODUCTS[name])


def _months_between(d1, d2):
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def _curve_metrics(df: pd.DataFrame, n: int):
    """Front/back, roll and annualized carry for the first n contracts."""
    d = df.copy()
    d["_date"] = d["Month"].map(_month_to_date)
    d = d.dropna(subset=["_date"]).sort_values("_date").reset_index(drop=True)
    view = d.head(n)
    if view.empty:
        return None
    front, back = view["Settle"].iloc[0], view["Settle"].iloc[-1]
    fm, bm = view["Month"].iloc[0], view["Month"].iloc[-1]
    m = {"view": view, "front": front, "back": back, "fm": fm, "bm": bm,
         "shape": "Backwardation" if back < front else
                  "Contango" if back > front else "Flat",
         "roll": None, "roll_pct": None, "roll_ann": None, "carry_ann": None}
    if len(view) > 1:
        a, b = view.iloc[0], view.iloc[1]
        m["roll"] = a["Settle"] - b["Settle"]
        m["roll_pct"] = m["roll"] / b["Settle"] * 100 if b["Settle"] else 0
        step = _months_between(a["_date"], b["_date"]) or 1
        m["roll_ann"] = m["roll_pct"] * (12 / step)
        span = _months_between(view["_date"].iloc[0], view["_date"].iloc[-1]) or 1
        m["carry_ann"] = (front - back) / back * (12 / span) * 100 if back else 0
    return m


@st.cache_data(ttl=1800, show_spinner=False)
def build_curve_scanner(n: int = 12) -> pd.DataFrame:
    rows = []
    for name in ALL_CURVE:
        try:
            m = _curve_metrics(get_curve_for(name), n)
        except Exception:  # noqa: BLE001
            m = None
        if not m:
            continue
        rows.append({
            "Symbol": name.split()[0],
            "Front": round(m["front"], 2),
            "Back": round(m["back"], 2),
            "Shape": m["shape"],
            "Roll ann %": round(m["roll_ann"], 1) if m["roll_ann"] is not None else None,
            "Carry ann %": round(m["carry_ann"], 1) if m["carry_ann"] is not None else None,
        })
    d = pd.DataFrame(rows)
    return d.sort_values("Carry ann %", ascending=False).reset_index(drop=True) \
        if not d.empty else d


def render_curve() -> None:
    st.caption(
        "Term structure from CME settlements. Positive carry = backwardation "
        "(roll tailwind for longs); negative = contango (roll drag)."
    )

    def pct_colour(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "color:#9ca3af;"
        return "color:#16a34a;font-weight:600;" if v >= 0 else "color:#dc2626;font-weight:600;"

    # --- ranked carry scanner (all symbols, 12M) ---
    st.markdown("##### Curve scanner — 12M carry, most backwardated first")
    scan = build_curve_scanner(12)
    if scan.empty:
        st.warning("Curve data unavailable — CME may be rate-limiting this "
                   "server's IP. Try Refresh in a few minutes; if it persists "
                   "we'll switch to a snapshot fetched via GitHub Actions.")
    else:
        st.dataframe(
            scan.style.map(pct_colour, subset=["Roll ann %", "Carry ann %"])
            .format({"Roll ann %": lambda v: "—" if v is None or pd.isna(v) else f"{v:+.1f}%",
                     "Carry ann %": lambda v: "—" if v is None or pd.isna(v) else f"{v:+.1f}%"}),
            hide_index=True, use_container_width=True,
        )

    st.divider()

    # --- per-symbol detail ---
    name = st.selectbox("Symbol", ALL_CURVE)
    if st.button("🔄 Refresh curve"):
        get_curve.clear()
        get_ice_curve.clear()
        build_curve_scanner.clear()
        st.rerun()
    try:
        df = get_curve_for(name)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't load curve: {str(e)[:80]}")
        return
    if df.empty:
        st.info("No settlement data returned.")
        with st.expander("🔧 Debug: raw response"):
            try:
                st.code(get_curve_raw_for(name)[:1500])
            except Exception as e:  # noqa: BLE001
                st.write(str(e))
        return

    horizon = st.radio("Horizon", ["12M", "24M", "36M", "All"], index=0,
                       horizontal=True)
    total = len(df.dropna(subset=["Settle"]))
    n = {"12M": 12, "24M": 24, "36M": 36, "All": total}[horizon]
    m = _curve_metrics(df, n)
    view = m["view"]

    # one-line hero
    arrow = ("↘" if m["shape"] == "Backwardation"
             else "↗" if m["shape"] == "Contango" else "→")
    parts = [f"**{name.split()[0]}**",
             f"{m['fm']} **{m['front']:,.2f}** → {m['bm']} **{m['back']:,.2f}**",
             f"{m['shape']} {arrow} {m['back'] - m['front']:+,.2f}"]
    if m["roll"] is not None:
        parts += [f"Roll {m['roll']:+,.2f} ({m['roll_pct']:+.2f}%)",
                  f"Roll ann {m['roll_ann']:+.1f}%",
                  f"Carry ann {m['carry_ann']:+.1f}%"]
    st.markdown("  ·  ".join(parts))

    # chart: settle line over OI bars
    view = view.copy()
    view["OI_num"] = view["OI"].map(_num)
    lo, hi = view["Settle"].min(), view["Settle"].max()
    pad = max((hi - lo) * 0.15, 0.5)
    order = list(view["Month"])
    base = alt.Chart(view).encode(
        x=alt.X("Month:N", sort=order, title=None,
                axis=alt.Axis(labelAngle=-45, labelFontSize=10)))
    bars = base.mark_bar(color="#cbd5e1", opacity=0.5).encode(
        y=alt.Y("OI_num:Q", axis=alt.Axis(title="Open interest", orient="right",
                                          grid=False)),
        tooltip=["Month", "Settle", "OI", "Volume"])
    line = base.mark_line(point=alt.OverlayMarkDef(size=35, filled=True),
                          color="#0d9488", strokeWidth=2.5).encode(
        y=alt.Y("Settle:Q", axis=alt.Axis(title="Settle", orient="left"),
                scale=alt.Scale(domain=[lo - pad, hi + pad])),
        tooltip=["Month", "Settle", "OI", "Volume"])
    chart = (alt.layer(bars, line).resolve_scale(y="independent")
             .properties(height=340).configure_view(strokeWidth=0)
             .configure_axis(labelColor="#6b7280", titleColor="#6b7280"))
    st.altair_chart(chart, use_container_width=True)
    st.table(view.drop(columns=["_date", "OI_num"]).style.hide(axis="index")
             .format({"Settle": lambda v: f"{v:,.2f}"}))


def main() -> None:
    st.title("🎋 Sakata")
    st.caption(f"Refreshed {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    tab_board, tab_margins, tab_events, tab_curve = st.tabs(
        ["Board", "Margins", "Events", "Curve"]
    )
    with tab_board:
        render_board()
    with tab_margins:
        render_margins()
    with tab_events:
        render_events()
    with tab_curve:
        render_curve()


if __name__ == "__main__":
    main()
