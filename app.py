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
import streamlit.components.v1 as components
import yfinance as yf
from curl_cffi import requests as cffi_requests

import base64
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_hex

st.set_page_config(page_title="Sakata", page_icon="🎋", layout="centered")

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

# News: overnight commentary blurb scraped per market from Trading Economics.
TE_NEWS = {
    "ES  S&P 500": "https://tradingeconomics.com/united-states/stock-market",
    "NKD  Nikkei": "https://tradingeconomics.com/japan/stock-market",
    "6E  Euro":    "https://tradingeconomics.com/euro-area/currency",
    "6J  Yen":     "https://tradingeconomics.com/japan/currency",
    "ZB  T-Bond":  "https://tradingeconomics.com/united-states/government-bond-yield",
    "CL  Crude":   "https://tradingeconomics.com/commodity/crude-oil",
    "NG  Nat Gas": "https://tradingeconomics.com/commodity/natural-gas",
    "GC  Gold":    "https://tradingeconomics.com/commodity/gold",
    "SI  Silver":  "https://tradingeconomics.com/commodity/silver",
    "HG  Copper":  "https://tradingeconomics.com/commodity/copper",
    "ZS  Soybean": "https://tradingeconomics.com/commodity/soybeans",
    "ZW  Wheat":   "https://tradingeconomics.com/commodity/wheat",
}

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


def build_scanner() -> pd.DataFrame:
    rows = []
    for sector, members in SECTORS.items():
        for name, (ticker, dec) in members.items():
            p = get_perf(ticker)
            last = p.get("last")
            rows.append({
                "Instrument": name.strip(), "Sector": sector,
                "Last": f"{last:,.{dec}f}" if last else "—",
                "Day %": p.get("day", float("nan")),
                "WTD %": p.get("wtd", float("nan")),
                "MTD %": p.get("mtd", float("nan")),
                "QTD %": p.get("qtd", float("nan")),
                "YTD %": p.get("ytd", float("nan")),
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
    # Indices
    "ES  S&P 500": 133,
    "NQ  Nasdaq":  146,
    # Bonds
    "ZB  T-Bond":  307,
    "ZN  10Y Note": 316,
    # Currencies
    "6E  Euro":    58,
    "6J  Yen":     69,
    # Crypto
    "BTC  Bitcoin": 8478,
    "ETH  Ether":  8995,
    # Energy
    "CL  Crude":   425,
    "NG  Nat Gas": 444,
    # Metals
    "GC  Gold":    437,
    "SI  Silver":  458,
    "HG  Copper":  438,
    # Grains
    "ZC  Corn":    300,
    "ZW  Wheat":   323,
    "ZS  Soybean": 320,
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



# --------------------------------------------------------------------------- #
# News — overnight commentary blurb per market, scraped from Trading Economics.
# Every TE market page is server-rendered and its lead paragraph == the first
# item in its News Stream, so one parser handles all URLs (no API key). The
# curl_cffi chrome session clears TE's bot wall — same trick that beats AMP.
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=900, show_spinner=False)
def get_te_commentary(url: str) -> dict:
    """Return the overnight commentary blurb (+ headline, date, link) from a TE
    market page — the body of the first /news/<id> item, which is the same text
    as the page's lead summary paragraph."""
    import re
    html = _session.get(url, timeout=25).text
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"headline": "", "blurb": "", "date": "", "url": url,
                "err": "pip install beautifulsoup4"}
    soup = BeautifulSoup(html, "html.parser")

    anchor = None
    for a in soup.select("a[href*='/news/']"):
        if re.search(r"/news/\d+", a.get("href", "")) and a.get_text(strip=True):
            anchor = a
            break
    if anchor is None:
        return {"headline": "", "blurb": "", "date": "", "url": url}

    headline = anchor.get_text(strip=True)
    href = anchor.get("href", "")
    link = href if href.startswith("http") else "https://tradingeconomics.com" + href

    blurb, date, node = "", "", anchor
    for _ in range(5):          # climb until one item is bracketed by headline..date
        node = node.find_parent()
        if node is None:
            break
        txt = node.get_text(" ", strip=True)
        i = txt.find(headline)
        after = txt[i + len(headline):] if i >= 0 else txt
        if (dm := re.search(r"(20\d\d-\d\d-\d\d)", after)) and dm.start() > 40:
            blurb = after[:dm.start()].strip()
            date = dm.group(1)
            break
    return {"headline": headline, "blurb": blurb, "date": date, "url": link}


def render_news() -> None:
    st.caption(
        "Overnight commentary per market — the lead blurb scraped from the "
        "selected Trading Economics page. Cached 15 min. Locally your chrome "
        "session clears TE's bot wall; a blank means the datacenter IP."
    )
    c1, c2 = st.columns([4, 1])
    with c1:
        label = st.selectbox("Symbol", list(TE_NEWS), label_visibility="collapsed")
    with c2:
        if st.button("Refresh", key="rn"):
            get_te_commentary.clear()
            st.rerun()

    st.markdown(f"##### {label}")
    try:
        d = get_te_commentary(TE_NEWS[label])
    except Exception as e:  # noqa: BLE001
        st.caption(f"— fetch failed: {str(e)[:60]}")
        return
    if not d.get("blurb"):
        st.caption(f"— {d.get('err') or 'nothing parsed (likely bot-blocked on this IP)'}")
        return
    st.markdown(d["blurb"])
    meta = "  ·  ".join(x for x in (d.get("date", ""),
                        f"[Trading Economics]({d['url']})") if x)
    st.markdown(f"<span style='color:#94a3b8;font-size:11px'>{meta}</span>",
                unsafe_allow_html=True)


def render_board() -> None:
    df = build_scanner()
    horizons = ["Day %", "WTD %", "MTD %", "QTD %", "YTD %"]

    def pct_colour(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "color:#9ca3af;"
        return "color:#16a34a;font-weight:600;" if v >= 0 else "color:#dc2626;font-weight:600;"

    def fmt_pct(v):
        return "—" if v is None or pd.isna(v) else f"{v:+.2f}%"

    fmt_map = {h: fmt_pct for h in horizons}

    # controls row
    c1, c2 = st.columns([4, 1])
    with c1:
        hz = st.radio("Horizon", horizons, index=0, horizontal=True,
                      label_visibility="collapsed")
    with c2:
        if st.button("Refresh", key="rb"):
            st.cache_data.clear()
            st.rerun()

    # --- sector performance: horizontal bar chart ---
    st.markdown(f"##### Sector performance · {hz}")
    agg = (df.groupby("Sector", sort=False)[horizons].mean().reset_index())
    agg["_v"] = agg[hz]
    agg = agg.sort_values("_v", ascending=False)
    bar = (alt.Chart(agg).mark_bar(cornerRadius=2, height=16).encode(
        x=alt.X("_v:Q", title=None, axis=alt.Axis(format="+.1f", grid=True,
                gridColor="#f1f5f9")),
        y=alt.Y("Sector:N", sort=list(agg["Sector"]), title=None,
                axis=alt.Axis(labelFontSize=12, labelColor="#334155")),
        color=alt.condition("datum._v >= 0", alt.value("#16a34a"), alt.value("#dc2626")),
        tooltip=[alt.Tooltip("Sector:N"), alt.Tooltip("_v:Q", format="+.2f", title=hz)],
    ).properties(height=28 * len(agg) + 10).configure_view(strokeWidth=0)
        .configure_axis(labelColor="#64748b"))
    st.altair_chart(bar, use_container_width=True)

    # --- full scanner (tight table, all rows in one shot) ---
    st.markdown("##### Scanner")
    st.table(
        df.style.map(pct_colour, subset=horizons).format(fmt_map).hide(axis="index")
    )


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
            "Roll %": round(m["roll_pct"], 2) if m["roll_pct"] is not None else None,
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

    def fmt_pct(v):
        return "—" if v is None or pd.isna(v) else f"{v:+.1f}%"

    def fmt_roll(v):
        return "—" if v is None or pd.isna(v) else f"{v:+,.2f}"

    def fmt_pct2(v):
        return "—" if v is None or pd.isna(v) else f"{v:+.2f}%"

    # --- input selections on top ---
    c1, c2 = st.columns([2, 3])
    with c1:
        horizon = st.radio("Horizon", ["12M", "24M", "36M", "All"], index=0,
                           horizontal=True)
    with c2:
        name = st.selectbox("Symbol", ALL_CURVE)
    if st.button("Refresh", key="rc"):
        get_curve.clear()
        get_ice_curve.clear()
        build_curve_scanner.clear()
        st.rerun()
    n = {"12M": 12, "24M": 24, "36M": 36, "All": 999}[horizon]

    # --- ranked carry scanner (title reflects the selected horizon) ---
    st.markdown(f"##### Curve scanner — {horizon} carry, most backwardated first")
    scan = build_curve_scanner(n)
    if scan.empty:
        st.warning("Curve data unavailable — CME may be rate-limiting this "
                   "server's IP. Try Refresh in a few minutes.")
    else:
        st.table(
            scan.style.map(pct_colour, subset=["Roll %", "Carry ann %"])
            .format({"Roll %": fmt_pct2, "Carry ann %": fmt_pct,
                     "Front": "{:,.2f}", "Back": "{:,.2f}"}).hide(axis="index")
        )

    st.divider()

    # --- per-symbol detail (same horizon) ---
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

    m = _curve_metrics(df, n)
    view = m["view"]

    # one-line hero: Current Roll, then Carry annualized
    arrow = ("↘" if m["shape"] == "Backwardation"
             else "↗" if m["shape"] == "Contango" else "→")
    parts = [f"**{name.split()[0]}**",
             f"{m['fm']} **{m['front']:,.2f}** → {m['bm']} **{m['back']:,.2f}**",
             f"{m['shape']} {arrow} {m['back'] - m['front']:+,.2f}"]
    if m["roll"] is not None:
        parts += [f"Current roll {m['roll_pct']:+.2f}%",
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


# =========================================================================== #
# Technical Analysis  —  Range Levels engine (matrix · breakdown · drill-down)
# Three legs per horizon: range regime · retrace rails · MA100/200 trend -> score -3..+3.
# =========================================================================== #
TA_INK, TA_TEAL = "#0f172a", "#0f766e"
TA_GREEN, TA_RED, TA_AMBER = "#15803d", "#b91c1c", "#c8922e"
TA_GREY, TA_LIVE = "#94a3b8", "#fef9ec"
TA_FONT = "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
TA_HEAT = LinearSegmentedColormap.from_list(
    "ta_heat", ["#c15a52", "#dfa79c", "#f0d7cf", "#f5f3ee", "#cbdcc7", "#93bb9d", "#4f9673"])
TA_DASH = "\u2013"
TA_LEN1, TA_LEN2 = 100, 200
TA_CHART_BARS = 180

TA_LADDER = {
    "Intra-Day":     dict(bar="1h",  seg="D", period="730d", note="1H bars"),
    "Intra-Week":    dict(bar="1h",  seg="W", period="730d", note="1H bars"),
    "Intra-Month":   dict(bar="4h",  seg="M", period="730d", note="4H bars"),
    "Intra-Quarter": dict(bar="1d",  seg="Q", period="10y",  note="1D bars"),
    "Intra-Year":    dict(bar="1wk", seg="Y", period="max",  note="1W bars"),
}
TA_ORDER = ["Intra-Day", "Intra-Week", "Intra-Month", "Intra-Quarter", "Intra-Year"]  # Day -> Year
TA_SHORT = {"Intra-Day": "Day", "Intra-Week": "Week", "Intra-Month": "Month",
            "Intra-Quarter": "Qtr", "Intra-Year": "Year"}
TA_DEFAULT = ["ES  S&P 500", "NQ  Nasdaq", "ZB  T-Bond", "6E  Euro",
              "BTC  Bitcoin", "CL  Crude", "GC  Gold", "ZC  Corn"]


# --------------------------------------------------------------- data + core
@st.cache_data(ttl=600, show_spinner=False)
def ta_fetch(sym: str, bar: str, period: str):
    native = "1h" if bar == "4h" else bar
    try:
        df = yf.Ticker(sym, session=_session).history(
            period=period, interval=native, auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df.columns = [str(c).lower() for c in df.columns]
    if not {"open", "high", "low", "close"}.issubset(df.columns):
        return None
    df = df[["open", "high", "low", "close"]].dropna()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    if bar == "4h":
        df = (df.resample("4h", label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna())
    return df


def ta_levels(df, seg):
    o = df.copy()
    o["seg"] = o.index.to_period(seg)
    g = o.groupby("seg", sort=True)
    o["cur_high"]  = g["high"].cummax()
    o["cur_low"]   = g["low"].cummin()
    o["prev_high"] = o["seg"].map(g["high"].max().shift(1))
    o["prev_low"]  = o["seg"].map(g["low"].min().shift(1))
    o["mid"] = (o.prev_high + o.prev_low) / 2
    o["rb"]  = (o.cur_high + o.prev_low) / 2
    o["rs"]  = (o.cur_low + o.prev_high) / 2
    o["ma1"] = o.close.rolling(TA_LEN1).mean()
    o["ma2"] = o.close.rolling(TA_LEN2).mean()
    o["pos"] = (o.close - o.prev_low) / (o.prev_high - o.prev_low) * 100
    return o.dropna(subset=["prev_high"])


def ta_read(r):
    if   r.pos > 100: regime, s_rng = "Breakout",   1
    elif r.pos <   0: regime, s_rng = "Breakdown", -1
    else:             regime, s_rng = "Range",      0
    hi, lo = max(r.rb, r.rs), min(r.rb, r.rs)
    if   r.close > hi: retrace, s_ret = "Bull",    1
    elif r.close < lo: retrace, s_ret = "Bear",   -1
    else:              retrace, s_ret = "Neutral", 0
    v100 = "above" if r.close > r.ma1 else "below"
    v200 = "above" if r.close > r.ma2 else "below"
    if   v100 == v200 == "above": trend, s_ma = "Bull",    1
    elif v100 == v200 == "below": trend, s_ma = "Bear",   -1
    else:                         trend, s_ma = "Neutral", 0
    score = s_rng + s_ret + s_ma
    bias = ("Strong Long" if score == 3 else "Long" if score == 2 else "Long tilt" if score == 1
            else "Short tilt" if score == -1 else "Short" if score == -2
            else "Strong Short" if score == -3 else "Neutral")
    return dict(regime=regime, retrace=retrace, trend=trend, v100=v100, v200=v200,
                score=score, bias=bias)


def ta_rr(r):
    nan = dict(rb_stop=np.nan, rs_tgt=np.nan, rr_retrace=np.nan, rr_range=np.nan)
    if not (0 <= r.pos <= 100):
        return nan
    px = r.close
    lo, hi = min(r.rb, r.rs), max(r.rb, r.rs)
    rr_r = (hi - px) / (px - lo) if (px > lo and hi > px) else np.nan
    rr_g = ((r.prev_high - px) / (px - r.prev_low)
            if (px > r.prev_low and r.prev_high > px) else np.nan)
    return dict(rb_stop=lo, rs_tgt=hi, rr_retrace=rr_r, rr_range=rr_g)


def _ta_lab(p):
    return p.start_time.strftime("%d %b %y") if p.freqstr.startswith("W") else str(p)


def _ta_sign(v):
    return (v > 0) - (v < 0)


def _ta_last(sym, tf):
    """Return (levels_frame o, last row r) for one instrument+horizon, or (None, None)."""
    cfg = TA_LADDER[tf]
    df = ta_fetch(sym, cfg["bar"], cfg["period"])
    if df is None or len(df) < TA_LEN2 + 5:
        return None, None
    o = ta_levels(df, cfg["seg"])
    if o.empty:
        return None, None
    return o, o.iloc[-1]


# --------------------------------------------------------------- scanner rows
def _ta_row(name, note, dec, o, r):
    chg = (o.close.iloc[-1] / o.close.iloc[-2] - 1) * 100 if len(o) >= 2 else np.nan
    return dict(rung=name, note=note, dec=dec, close=r.close, chg=chg,
                high=r.prev_high, low=r.prev_low,
                rngpct=(r.prev_high - r.prev_low) / r.prev_low * 100,
                pos=r.pos, mid=r.mid, rb=r.rb, rs=r.rs, ma100=r.ma1, ma200=r.ma2,
                **ta_read(r), **ta_rr(r))


def ta_scan_rows(basket, tf):
    rows = []
    for lbl in basket:
        sym, dec = SYMBOLS[lbl][0], SYMBOLS[lbl][1]
        o, r = _ta_last(sym, tf)
        if r is None:
            continue
        rows.append(_ta_row(lbl, TA_LADDER[tf]["note"], dec, o, r))
    rows.sort(key=lambda x: (x["score"], x["pos"]), reverse=True)
    for i, x in enumerate(rows, 1):
        x["rung"] = f"{i}. {x['rung']}"
    return rows


# --------------------------------------------------------------- scanner HTML
def ta_scanner_html(rows, title, first_col="Asset"):
    posn, scorn = Normalize(-20, 120), Normalize(-3, 3)
    chgn = Normalize(-3, 3)
    mc  = lambda v: TA_GREEN if v == "above" else TA_RED
    sig = lambda v: TA_GREEN if v == "Bull" else TA_RED if v == "Bear" else "#697683"
    rc  = {"Breakout": TA_GREEN, "Breakdown": TA_RED, "Range": "#697683"}
    bc  = lambda b: TA_GREEN if "Long" in b else TA_RED if "Short" in b else "#697683"
    def rrc(v):
        if not np.isfinite(v): return TA_GREY
        return TA_GREEN if v >= 2 else TA_AMBER if v >= 1 else TA_RED
    fnum = lambda v, d: f"{v:,.{d}f}"
    nz   = lambda v, f: TA_DASH if not np.isfinite(v) else f(v)
    chg_hex = lambda v: to_hex(TA_HEAT(chgn(v))) if np.isfinite(v) else "#f5f3ee"
    chgc = lambda v: (TA_GREEN if (np.isfinite(v) and v > 0)
                      else TA_RED if (np.isfinite(v) and v < 0) else TA_GREY)
    def chg_txt(v):
        if not np.isfinite(v): return TA_DASH
        a = "\u25b2" if v > 0 else "\u25bc" if v < 0 else ""
        return f"{a} {v:+.2f}%"

    h = [f'<div style="font-family:{TA_FONT};font-variant-numeric:tabular-nums;'
         f'border-left:3px solid {TA_TEAL};padding-left:10px;margin-bottom:8px;">',
         f'<div style="font-size:12px;font-weight:700;color:{TA_INK};margin-bottom:9px;">{title}</div>',
         '<table style="border-collapse:separate;border-spacing:0;box-shadow:0 1px 4px '
         'rgba(20,40,80,.08);border-radius:8px;overflow:hidden;"><thead><tr>']
    heads = [(first_col, "left"), ("Last", "right"), ("Chg %", "right"),
             ("Rng Hi", "right"), ("Rng Lo", "right"), ("In Rng %", "right"),
             ("RB", "right"), ("RS", "right"),
             ("Regime", "left"), ("Retrace", "left"), ("Trend", "left"), ("Score", "right"),
             ("Bias", "left"), ("R:R Ret", "right"), ("R:R Rng", "right")]
    for c, a in heads:
        h.append(f'<th style="background:{TA_INK};color:#9fb4cd;text-align:{a};font-size:8px;'
                 f'font-weight:600;letter-spacing:.03em;text-transform:uppercase;'
                 f'padding:4px 6px;white-space:nowrap;">{c}</th>')
    h.append('</tr></thead><tbody>')

    for r in rows:
        d = r["dec"]
        def td(v, a="right", col="#20242b", w="600", extra=""):
            return (f'<td style="padding:4px 6px;text-align:{a};font-size:9.5px;color:{col};'
                    f'font-weight:{w};white-space:nowrap;border-bottom:1px solid #eef1f5;{extra}">{v}</td>')
        h.append("<tr>"
            + td(f'{r["rung"]}<span style="color:{TA_GREY};font-weight:500;"> \u00b7 {r["note"]}</span>',
                 "left", "#20242b", "700", "border-right:1px solid #e7ebf0;")
            + td(fnum(r["close"], d), "right", "#141922", "800",
                 f'font-size:10.5px;background:{chg_hex(r.get("chg", np.nan))};')
            + td(chg_txt(r.get("chg", np.nan)), "right", chgc(r.get("chg", np.nan)), "700",
                 "border-right:2px solid #e3e8ef;")
            + td(fnum(r["high"], d), col=TA_GREEN)
            + td(fnum(r["low"], d),  col=TA_RED)
            + td(f'{r["pos"]:,.0f}', "right", "#20242b", "700",
                 f'background:{to_hex(TA_HEAT(posn(r["pos"])))};border-right:1px solid #e7ebf0;')
            + td(fnum(r["rb"], d),  col="#17608f")
            + td(fnum(r["rs"], d),  col="#8a6008", extra="border-right:1px solid #e7ebf0;")
            + td(r["regime"],  "left", rc[r["regime"]], "700")
            + td(r["retrace"], "left", sig(r["retrace"]), "700")
            + td(r["trend"],   "left", sig(r["trend"]), "700")
            + td(f'{r["score"]:+d}', "right", "#20242b", "700",
                 f'background:{to_hex(TA_HEAT(scorn(r["score"])))};')
            + td(r["bias"], "left", bc(r["bias"]), "700", "border-right:1px solid #e7ebf0;")
            + td(nz(r["rr_retrace"], lambda v: f"{v:,.2f}"), "right", rrc(r["rr_retrace"]), "700")
            + td(nz(r["rr_range"],   lambda v: f"{v:,.2f}"), "right", rrc(r["rr_range"]), "700")
            + "</tr>")
    h.append('</tbody></table></div>')
    return "".join(h)


# --------------------------------------------------------------- matrix
def ta_grid_for(label):
    sym = SYMBOLS[label][0]
    cells = {}
    for tf in TA_ORDER:
        o, r = _ta_last(sym, tf)
        if r is None:
            cells[tf] = None; continue
        info = ta_read(r)
        cells[tf] = dict(score=int(info["score"]), bias=info["bias"],
                         regime=info["regime"], pos=float(r.pos))
    return cells


def ta_matrix_html(grid):
    scorn, rown, coln = Normalize(-3, 3), Normalize(-9, 9), Normalize(-14, 14)
    tfs = TA_ORDER
    col_tot = {tf: 0 for tf in tfs}
    rows = []
    for label, cells in grid.items():
        scores = [cells[tf]["score"] for tf in tfs if cells.get(tf)]
        if not scores:
            continue
        rtot = sum(scores)
        signs = [_ta_sign(s) for s in scores if s != 0]
        if   not signs:                 tag, tagc = "flat",          TA_GREY
        elif all(v > 0 for v in signs): tag, tagc = "aligned long",  TA_GREEN
        elif all(v < 0 for v in signs): tag, tagc = "aligned short", TA_RED
        else:                           tag, tagc = "mixed",         TA_AMBER
        for tf in tfs:
            c = cells.get(tf)
            if c: col_tot[tf] += c["score"]
        rows.append(dict(name=label, cells=cells, rtot=rtot, tag=tag, tagc=tagc))
    rows.sort(key=lambda x: x["rtot"], reverse=True)
    grand = sum(col_tot.values())

    def th(txt, a="center"):
        return (f'<th style="background:{TA_INK};color:#9fb4cd;text-align:{a};font-size:8.5px;'
                f'font-weight:600;letter-spacing:.04em;text-transform:uppercase;'
                f'padding:7px 10px;white-space:nowrap;">{txt}</th>')

    h = [f'<div style="font-family:{TA_FONT};font-variant-numeric:tabular-nums;'
         f'border-left:3px solid {TA_TEAL};padding-left:10px;margin-bottom:6px;">',
         '<table style="border-collapse:separate;border-spacing:0;box-shadow:0 1px 4px '
         'rgba(20,40,80,.08);border-radius:8px;overflow:hidden;"><thead><tr>',
         th("Instrument", "left")]
    for tf in tfs:
        h.append(th(TA_SHORT[tf]))
    h.append(th("Conv") + th("Read", "left"))
    h.append('</tr></thead><tbody>')

    for row in rows:
        cells = row["cells"]
        h.append("<tr>")
        h.append(f'<td style="padding:7px 11px;text-align:left;font-size:10.5px;font-weight:700;'
                 f'color:#20242b;white-space:nowrap;border-bottom:1px solid #eef1f5;'
                 f'border-right:1px solid #e7ebf0;">{row["name"]}</td>')
        for tf in tfs:
            c = cells.get(tf)
            if not c:
                h.append(f'<td style="padding:7px 10px;text-align:center;color:{TA_GREY};'
                         f'font-size:10px;border-bottom:1px solid #eef1f5;">{TA_DASH}</td>')
                continue
            bg  = to_hex(TA_HEAT(scorn(c["score"])))
            tip = f'{c["bias"]} \u00b7 {c["regime"]} \u00b7 {c["pos"]:.0f}% in range'
            h.append(f'<td title="{tip}" style="padding:7px 10px;text-align:center;font-size:11px;'
                     f'font-weight:800;color:#141922;background:{bg};'
                     f'border-bottom:1px solid #eef1f5;cursor:default;">{c["score"]:+d}</td>')
        h.append(f'<td style="padding:7px 10px;text-align:center;font-size:11px;font-weight:800;'
                 f'color:#141922;background:{to_hex(TA_HEAT(rown(row["rtot"])))};'
                 f'border-left:1px solid #e7ebf0;border-bottom:1px solid #eef1f5;">{row["rtot"]:+d}</td>')
        h.append(f'<td style="padding:7px 11px;text-align:left;font-size:10px;font-weight:700;'
                 f'color:{row["tagc"]};white-space:nowrap;border-bottom:1px solid #eef1f5;">'
                 f'{row["tag"]}</td>')
        h.append("</tr>")

    h.append(f'<tr><td style="padding:7px 11px;text-align:left;font-size:9px;font-weight:700;'
             f'letter-spacing:.04em;text-transform:uppercase;color:#9fb4cd;background:{TA_INK};">'
             f'Breadth</td>')
    for tf in tfs:
        v = col_tot[tf]
        h.append(f'<td style="padding:7px 10px;text-align:center;font-size:10.5px;font-weight:800;'
                 f'color:#141922;background:{to_hex(TA_HEAT(coln(v)))};">{v:+d}</td>')
    h.append(f'<td style="padding:7px 10px;text-align:center;font-size:11px;font-weight:800;'
             f'color:white;background:{TA_INK};">{grand:+d}</td>')
    h.append(f'<td style="background:{TA_INK};"></td></tr></tbody></table></div>')
    return "".join(h), rows, col_tot, grand


def ta_matrix_read(rows, col_tot, grand):
    tfs = TA_ORDER
    longs  = [r for r in rows if r["rtot"] > 0]
    shorts = [r for r in rows if r["rtot"] < 0]
    mixed  = [r for r in rows if r["tag"] == "mixed"]
    top_long  = rows[0]  if rows and rows[0]["rtot"]  > 0 else None
    top_short = rows[-1] if rows and rows[-1]["rtot"] < 0 else None
    most_conf = min(mixed, key=lambda r: abs(r["rtot"])) if mixed else None
    posture = "net long" if grand > 2 else "net short" if grand < -2 else "balanced"
    risk_on  = [TA_SHORT[tf] for tf in tfs if col_tot[tf] > 0]
    risk_off = [TA_SHORT[tf] for tf in tfs if col_tot[tf] < 0]

    def line(lead, body, col=TA_INK):
        return (f'<div style="margin:2px 0;font-size:11px;"><b style="color:{col}">{lead}</b> '
                f'<span style="color:#3a4149">{body}</span></div>')

    p = [f'<div style="font-family:{TA_FONT};border-left:3px solid {TA_AMBER};padding:8px 12px;'
         f'margin-bottom:12px;background:{TA_LIVE};border-radius:6px;">']
    p.append(line("Basket posture \u2014",
        f'net score {grand:+d} across {len(rows)} instruments \u00d7 {len(tfs)} horizons '
        f'({posture}). {len(longs)} long-biased, {len(shorts)} short-biased.'))
    if risk_on:
        p.append(line("Risk-on horizons \u2014", ", ".join(risk_on), TA_GREEN))
    if risk_off:
        p.append(line("Risk-off horizons \u2014", ", ".join(risk_off), TA_RED))
    if top_long:
        p.append(line("Strongest long alignment \u2014",
                      f'{top_long["name"]} at {top_long["rtot"]:+d}.', TA_GREEN))
    if top_short:
        p.append(line("Strongest short alignment \u2014",
                      f'{top_short["name"]} at {top_short["rtot"]:+d}.', TA_RED))
    if most_conf:
        p.append(line("Most conflicted \u2014",
                      f'{most_conf["name"]} (horizons disagree, net {most_conf["rtot"]:+d}) '
                      f'\u2014 transition / mean-revert candidate.', TA_AMBER))
    p.append('</div>')
    return "".join(p)


# --------------------------------------------------------------- drill-down
def ta_seg_table(o, n):
    g = o.groupby("seg", sort=True)
    t = pd.DataFrame({"Bars": g.close.size(), "High": g.high.max(), "Low": g.low.min(),
                      "Close": g.close.last(), "MA100": g.ma1.last(), "MA200": g.ma2.last()})
    t["Range %"] = (t.High - t.Low) / t.Low * 100
    t["Chg %"]   = t.Close.pct_change() * 100
    ph, pl = t.High.shift(), t.Low.shift()
    t["vs prior range"] = np.select([t.Close > ph, t.Close < pl],
                                    ["broke out", "broke down"], default="held inside")
    t["vs 100"] = np.where(t.Close > t.MA100, "above", "below")
    t["vs 200"] = np.where(t.Close > t.MA200, "above", "below")
    t.index = [_ta_lab(p) for p in t.index]; t.index.name = "Segment"
    t = t[["Bars", "High", "Low", "Range %", "Close", "Chg %", "vs prior range",
           "MA100", "vs 100", "MA200", "vs 200"]].tail(n)
    return t.iloc[::-1]


def ta_style_grid(t, caption, dec):
    def _css(dfin):
        s = pd.DataFrame("", index=dfin.index, columns=dfin.columns)
        s["Chg %"] = [f"color:{TA_GREEN};font-weight:600" if v > 0 else f"color:{TA_RED};font-weight:600"
                      for v in dfin["Chg %"].fillna(0)]
        s["High"], s["Low"] = f"color:{TA_GREEN}", f"color:{TA_RED}"
        s["Close"] = "color:#20242b;font-weight:700"
        s["vs prior range"] = [f"color:{TA_GREEN};font-weight:700" if v == "broke out"
                               else f"color:{TA_RED};font-weight:700" if v == "broke down"
                               else f"color:{TA_GREY}" for v in dfin["vs prior range"]]
        for c in ("vs 100", "vs 200"):
            s[c] = [f"color:{TA_GREEN};font-weight:600" if v == "above"
                    else f"color:{TA_RED};font-weight:600" for v in dfin[c]]
        for c in ("MA100", "MA200", "Bars", "Range %"):
            s[c] = f"color:{TA_GREY}"
        s.iloc[0] = s.iloc[0] + f";background:{TA_LIVE}"
        return s
    numf = f"{{:,.{dec}f}}"
    return (t.style.apply(_css, axis=None)
             .format({"High": numf, "Low": numf, "Close": numf, "MA100": numf, "MA200": numf,
                      "Range %": "{:,.1f}", "Chg %": "{:,.1f}", "Bars": "{:,.0f}"}, na_rep=TA_DASH)
             .set_caption(caption)
             .set_table_styles([
                {"selector": "", "props": [("font-family", TA_FONT), ("border-collapse", "separate"),
                    ("border-spacing", "0"), ("font-variant-numeric", "tabular-nums"),
                    ("box-shadow", "0 1px 4px rgba(20,40,80,.08)"), ("border-radius", "8px"),
                    ("overflow", "hidden"), ("margin", "0"), ("white-space", "nowrap"),
                    ("border-left", f"3px solid {TA_TEAL}")]},
                {"selector": "caption", "props": [("caption-side", "top"), ("font-size", "11px"),
                    ("font-weight", "700"), ("color", TA_INK), ("padding", "0 0 8px 1px"),
                    ("text-align", "left")]},
                {"selector": "thead th", "props": [("background", TA_INK), ("color", "#f4f7fb"),
                    ("font-weight", "600"), ("padding", "5px 9px"), ("text-align", "right"),
                    ("font-size", "9.5px"), ("border", "none"), ("white-space", "nowrap")]},
                {"selector": "th.index_name", "props": [("background", TA_INK), ("color", "#f4f7fb")]},
                {"selector": "th.row_heading", "props": [("background", "#f5f7fa"), ("color", "#3a4149"),
                    ("font-weight", "600"), ("padding", "5px 10px"), ("text-align", "left"),
                    ("font-size", "10px"), ("border", "none"), ("border-right", "1px solid #e7ebf0")]},
                {"selector": "th.row_heading.level0.row0",
                    "props": [("background", TA_LIVE), ("color", "#8a6008"), ("font-weight", "700"),
                              ("box-shadow", f"inset 3px 0 0 {TA_AMBER}")]},
                {"selector": "td.row0", "props": [("border-bottom", "1px solid #ead9ae")]},
                {"selector": "td", "props": [("padding", "5px 9px"), ("text-align", "right"),
                    ("font-size", "10px"), ("border", "none"), ("border-bottom", "1px solid #eef1f5")]},
                {"selector": "tbody tr:hover td:not(.row0)", "props": [("background", "#fbfcfe")]},
             ]))


def ta_chart_fig(o, name, dec, rr):
    d = o.tail(TA_CHART_BARS); x = np.arange(len(d)); r = d.iloc[-1]
    fig, ax = plt.subplots(figsize=(9.4, 3.15), dpi=150)
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")
    ax.fill_between(x, d.prev_low, d.prev_high, step="post", color=TA_INK, alpha=0.045, lw=0, zorder=0)
    if np.isfinite(rr["rr_retrace"]):
        ax.axhspan(rr["rb_stop"], r.close, color=TA_RED,   alpha=0.05, lw=0)
        ax.axhspan(r.close, rr["rs_tgt"],  color=TA_GREEN, alpha=0.05, lw=0)
    ax.step(x, d.prev_high, where="post", color=TA_GREEN, lw=1.4, zorder=3)
    ax.step(x, d.prev_low,  where="post", color=TA_RED,   lw=1.4, zorder=3)
    ax.step(x, d.mid, where="post", color="#c2c8d2", lw=1.0, ls=(0, (4, 3)), zorder=2)
    ax.step(x, d.rb,  where="post", color="#2f7fb5", lw=1.0, alpha=.75, zorder=2)
    ax.step(x, d.rs,  where="post", color=TA_AMBER,  lw=1.0, alpha=.75, zorder=2)
    ax.plot(x, d.ma1, color="#cfd5dd", lw=1.0, zorder=2)
    ax.plot(x, d.ma2, color="#aab2bd", lw=1.0, zorder=2)
    ax.plot(x, d.close, color=TA_TEAL, lw=1.7, zorder=6)
    ax.scatter([x[-1]], [r.close], s=24, color=TA_TEAL, zorder=7, edgecolor="white", linewidth=1.1)
    fm = lambda v: f"{v:,.{dec}f}"
    for lvl, col, txt in [(r.prev_high, TA_GREEN, "H"), (r.prev_low, TA_RED, "L"),
                          (r.mid, TA_GREY, "Mid"), (r.rb, "#2f7fb5", "RB"), (r.rs, TA_AMBER, "RS")]:
        ax.annotate(f"{txt} {fm(lvl)}", (x[-1], lvl), xytext=(8, 0), textcoords="offset points",
                    color=col, fontsize=7.2, va="center", fontweight="bold")
    ax.annotate(f"{fm(r.close)}", (x[-1], r.close), xytext=(8, 0), textcoords="offset points",
                color="white", fontsize=7.4, va="center", ha="left", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc=TA_TEAL, ec="none"))
    rrt = TA_DASH if not np.isfinite(rr["rr_retrace"]) else f'{rr["rr_retrace"]:,.2f}'
    ax.set_title(f"{name}   \u00b7   {fm(r.close)}   \u00b7   {r.pos:,.0f}% in range   \u00b7   R:R {rrt}",
                 color=TA_INK, fontsize=10, fontweight="bold", loc="left", pad=8)
    ax.grid(color="#eef1f5", lw=0.7)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color("#e2e6ec")
    ax.set_xticks([]); ax.set_xlim(-1, (len(d) - 1) + len(d) * 0.17)
    ax.tick_params(colors="#8b95a1", labelsize=7)
    fig.tight_layout(pad=0.4)
    return fig


# The free TradingView embed can't show CME/ICE futures data ("only available on
# TradingView"), so each instrument maps to a freely-embeddable proxy: US-listed
# ETF, spot, FX, or a TVC continuous index. Close enough for chart-reading; switch
# to the real contract in the chart's own search box if you have a TV data plan.
TV_SYM = {
    "ES  S&P 500": "AMEX:SPY",   "NQ  Nasdaq": "NASDAQ:QQQ",
    "ZB  T-Bond": "NASDAQ:TLT",  "ZN  10Y Note": "NASDAQ:IEF", "SR3  SOFR": "AMEX:SHV",
    "6E  Euro": "FX:EURUSD",     "6J  Yen": "FX:USDJPY",
    "BTC  Bitcoin": "BINANCE:BTCUSDT", "ETH  Ether": "BINANCE:ETHUSDT",
    "CL  Crude": "TVC:USOIL",    "NG  Nat Gas": "AMEX:UNG",
    "GC  Gold": "TVC:GOLD",      "SI  Silver": "TVC:SILVER", "HG  Copper": "AMEX:CPER",
    "ZC  Corn": "AMEX:CORN",     "ZW  Wheat": "AMEX:WEAT",   "ZS  Soybean": "AMEX:SOYB",
    "SB  Sugar": "AMEX:CANE",    "KC  Coffee": "AMEX:JO",
}
TV_DEFAULT = "AMEX:SPY"


def ta_tv_chart(tv_symbol, interval, cid, height=500):
    return (
        '<div class="tradingview-widget-container">'
        f'<div id="{cid}"></div>'
        '<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>'
        '<script type="text/javascript">new TradingView.widget({'
        f'"width":"100%","height":{height},'
        f'"symbol":"{tv_symbol}","interval":"{interval}",'
        '"timezone":"Asia/Singapore","theme":"light","style":"1","locale":"en",'
        '"hide_side_toolbar":false,"allow_symbol_change":true,"withdateranges":true,'
        f'"container_id":"{cid}"' '});</script></div>'
    )


def ta_render_drill(label):
    sym, dec = SYMBOLS[label][0], SYMBOLS[label][1]
    rows = []
    for tf in TA_ORDER:
        o, r = _ta_last(sym, tf)
        if r is None:
            continue
        rows.append(_ta_row(tf, TA_LADDER[tf]["note"], dec, o, r))
    if rows:
        st.markdown(ta_scanner_html(rows, f"{label} — range scanner", first_col="Horizon"),
                    unsafe_allow_html=True)
    tv = TV_SYM.get(label, TV_DEFAULT)
    st.caption(f"Chart proxy: **{tv}** — switch symbol or timeframe in the chart toolbar. "
               "Range-scanner numbers above are the live Yahoo read for the actual contract.")
    components.html(ta_tv_chart(tv, "D", "tv_main"), height=560)


# --------------------------------------------------------------- tab entry
def render_ta() -> None:
    st.caption(
        "Range-levels engine. Each horizon scores three legs — **range regime**, "
        "**retrace rails** (RB/RS), **MA100/200 trend** — into a −3…+3 bias. Screen the basket in the "
        "**matrix** (Day → Year), chart any name beside it, rank one horizon in the **breakdown**, "
        "then read exact levels below."
    )
    all_labels = list(SYMBOLS)
    c1, c2 = st.columns([5, 1])
    with c1:
        basket = st.multiselect("Basket", all_labels, default=TA_DEFAULT,
                                label_visibility="collapsed", key="ta_basket")
    with c2:
        if st.button("Refresh", key="rta"):
            ta_fetch.clear(); st.rerun()
    if not basket:
        st.info("Pick at least one instrument to scan."); return

    with st.spinner("Building matrix…"):
        grid = {lbl: ta_grid_for(lbl) for lbl in basket}
    table_html, rows, col_tot, grand = ta_matrix_html(grid)
    if not rows:
        st.warning("No data returned for the current basket."); return

    # basket read (full width)
    st.markdown(ta_matrix_read(rows, col_tot, grand), unsafe_allow_html=True)

    # 1 — MATRIX (full width)
    st.markdown("##### Alignment matrix · Day → Year · hover a cell for detail")
    st.markdown(f"<div style='overflow-x:auto'>{table_html}</div>", unsafe_allow_html=True)

    st.markdown("---")
    # 2 — TIMEFRAME BREAKDOWN (full width)
    st.markdown("##### Timeframe breakdown · full read at one horizon, strongest first")
    tf = st.radio("Horizon", TA_ORDER, index=0, horizontal=True,
                  format_func=lambda x: TA_SHORT[x], label_visibility="collapsed", key="ta_tf")
    with st.spinner(f"Scanning {TA_SHORT[tf]}…"):
        srows = ta_scan_rows(basket, tf)
    if srows:
        tf_title = f"{tf} ({TA_LADDER[tf]['note']})"
        st.markdown("<div style='overflow-x:auto'>"
                    + ta_scanner_html(srows, tf_title, first_col="Instrument")
                    + "</div>", unsafe_allow_html=True)
    else:
        st.warning(f"No data on {TA_SHORT[tf]} for this basket.")

    st.markdown("---")
    # 3 — INSTRUMENT FOCUS (selector drives chart + levels, all full width)
    st.markdown("##### Instrument focus")
    order = [r["name"] for r in rows]  # strongest conviction first
    asset = st.selectbox("Instrument", order, index=0, key="ta_asset")

    tv = TV_SYM.get(asset, TV_DEFAULT)
    st.markdown(f"<div style='font-size:12px;font-weight:700;color:{TA_INK};margin:2px 0 4px'>"
                f"{asset} \u00b7 <span style='color:#94a3b8;font-weight:500'>{tv}</span></div>",
                unsafe_allow_html=True)
    components.html(ta_tv_chart(tv, "D", "tv_main", 520), height=522)

    sym, dec = SYMBOLS[asset][0], SYMBOLS[asset][1]
    arows = []
    for h in TA_ORDER:
        o, r = _ta_last(sym, h)
        if r is None:
            continue
        arows.append(_ta_row(h, TA_LADDER[h]["note"], dec, o, r))
    if arows:
        st.markdown("<div style='overflow-x:auto;margin-top:10px'>"
                    + ta_scanner_html(arows, f"Levels · {asset} across every horizon", first_col="Horizon")
                    + "</div>", unsafe_allow_html=True)
    else:
        st.warning(f"No usable data for {asset}.")


_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"], .stMarkdown,
.stButton, input, textarea, select, [data-baseweb], [class*="st-"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
.block-container { padding-top: 2.4rem; padding-bottom: 2rem; max-width: 1060px; }

/* header */
.sakata-head { display:flex; align-items:center; gap:11px; border-bottom:2px solid #0f766e;
  padding-bottom:9px; margin-bottom:12px; }
.sakata-title { font-family:'Poppins',sans-serif !important; font-size:1.4rem; font-weight:700;
  letter-spacing:-0.01em; color:#0f172a; }
.sakata-sub { font-size:11px; color:#94a3b8; font-weight:500; letter-spacing:0.03em;
  margin-left:auto; text-transform:uppercase; }

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap:2px; border-bottom:1px solid #e5e7eb; }
.stTabs [data-baseweb="tab"] { height:38px; padding:0 20px; font-weight:600; font-size:13px;
  color:#64748b; letter-spacing:0.02em; }
.stTabs [aria-selected="true"] { color:#0f766e; }
.stTabs [data-baseweb="tab-highlight"] { background-color:#0f766e; height:2px; }

/* eyebrow subheaders */
.stMarkdown h5 { font-family:'Poppins',sans-serif !important; font-size:11px;
  text-transform:uppercase; letter-spacing:0.07em; color:#475569; font-weight:600;
  margin:10px 0 4px; }

/* buttons */
.stButton>button { border:1px solid #e2e8f0; border-radius:6px; padding:2px 15px;
  font-size:11px; font-weight:600; letter-spacing:0.05em; text-transform:uppercase;
  color:#475569; background:#fff; box-shadow:none; transition:all .12s; min-height:30px; }
.stButton>button:hover { border-color:#0f766e; color:#0f766e; background:#f0fdfa; }
.stButton>button:active, .stButton>button:focus { color:#0f766e; border-color:#0f766e;
  box-shadow:none; }

/* captions + controls */
[data-testid="stCaptionContainer"] { color:#64748b; font-size:12px; line-height:1.5; }
.stRadio [role="radiogroup"] label { font-size:12.5px; color:#334155; font-weight:500; }

/* tables (st.table) — tight but comfortable terminal density */
[data-testid="stTable"] { width:100%; overflow-x:auto; }
[data-testid="stTable"] table { width:auto; min-width:70%; font-size:12px;
  border-collapse:collapse; font-variant-numeric:tabular-nums; line-height:1.35; }
[data-testid="stTable"] thead th { background:#f8fafc; color:#64748b; font-weight:600;
  text-transform:uppercase; font-size:10px; letter-spacing:0.04em;
  border-bottom:1px solid #e2e8f0; padding:6px 12px !important; text-align:right; }
[data-testid="stTable"] thead th:first-child,
[data-testid="stTable"] tbody th { text-align:left; }
[data-testid="stTable"] td { padding:4px 12px !important; border-bottom:1px solid #f4f6f8;
  text-align:right; white-space:nowrap; color:#334155; }
[data-testid="stTable"] td:first-child { text-align:left; font-weight:500; color:#0f172a;
  padding-right:20px !important; }
[data-testid="stTable"] tbody tr:hover td { background:#f8fafc; }
[data-testid="stDataFrame"] { font-size:13px; border:1px solid #eef2f6; border-radius:8px; }
hr { margin:0.6rem 0; border-color:#eef2f6; }
</style>
"""

_LOGO = (
    '<svg width="30" height="30" viewBox="0 0 30 30" fill="none">'
    '<rect width="30" height="30" rx="7" fill="#0f172a"/>'
    # commodity bars (amber)
    '<rect x="6.5" y="17" width="3" height="7" rx="1" fill="#f59e0b"/>'
    '<rect x="13.5" y="14" width="3" height="10" rx="1" fill="#f59e0b"/>'
    '<rect x="20.5" y="11" width="3" height="13" rx="1" fill="#f59e0b"/>'
    # financial trend line (teal) weaving over the bars
    '<path d="M5 21 L11 13 L15 18 L19 9 L25 6" stroke="#2dd4bf" stroke-width="2.1" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="25" cy="6" r="2.1" fill="#2dd4bf"/>'
    '</svg>'
)


def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="sakata-head">{_LOGO}'
        f'<span class="sakata-title">Sakata</span>'
        f'<span class="sakata-sub">futures terminal · {dt.datetime.now():%Y-%m-%d %H:%M}</span>'
        f'</div>', unsafe_allow_html=True)
    tab_board, tab_ta, tab_margins, tab_events, tab_news, tab_curve = st.tabs(
        ["Board", "Technical", "Margins", "Events", "News", "Curve"]
    )
    with tab_board:
        render_board()
    with tab_ta:
        render_ta()
    with tab_margins:
        render_margins()
    with tab_events:
        render_events()
    with tab_news:
        render_news()
    with tab_curve:
        render_curve()


if __name__ == "__main__":
    main()
