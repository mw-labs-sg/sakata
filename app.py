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


def build_margins() -> pd.DataFrame:
    try:
        amp = get_amp_margins()
    except Exception as e:  # noqa: BLE001
        return pd.DataFrame([{"Instrument": "AMP ERROR", "Sym": "", "Exchange": "",
                              "Maint (USD)": str(e)[:60], "Day (USD)": "", "Source": ""}])
    rows = []
    for label in SYMBOLS:
        if label in AMP_SYMBOLS:
            sym = AMP_SYMBOLS[label]
            r = amp.get(sym)
            if r:
                rows.append({
                    "Instrument": label, "Sym": sym, "Exchange": r["exch"],
                    "Maint (USD)": f"{r['maint']:,.0f}" if r["maint"] else "—",
                    "Day (USD)": f"{r['day']:,.0f}" if r["day"] else "—",
                    "Source": "AMP",
                })
            else:
                rows.append({"Instrument": label, "Sym": sym, "Exchange": "—",
                             "Maint (USD)": "—", "Day (USD)": "—",
                             "Source": "AMP (missing)"})
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
    "CL  (Crude Oil)": 425,
    "NG  (Nat Gas)":   444,
    "GC  (Gold)":      437,
    "SI  (Silver)":    458,
    "ES  (S&P 500)":   133,
    "ZC  (Corn)":      300,
    "ZS  (Soybeans)":  320,
}


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


def _fetch_settlements(pid: int, trade_date: str) -> str:
    url = CURVE_URL.format(pid=pid) + f"?tradeDate={trade_date}"
    return _session.get(url, timeout=25, headers={"Accept": "application/json"}).text


def _recent_business_days(n: int = 6) -> list:
    days, d = [], _d.date.today()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= _d.timedelta(days=1)
    return days


_DATE_FMTS = ["%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"]


@st.cache_data(ttl=1800, show_spinner=False)
def get_curve(pid: int) -> pd.DataFrame:
    """Try recent trading days / date formats until CME returns the strip."""
    import json as _json
    for day in _recent_business_days():
        for fmt in _DATE_FMTS:
            try:
                raw = _fetch_settlements(pid, day.strftime(fmt))
                rows = _parse_settlements(_json.loads(raw))
                if rows:
                    return pd.DataFrame(rows)
            except Exception:  # noqa: BLE001
                continue
    return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def get_curve_raw(pid: int) -> str:
    """Raw response for the most recent business day (debug)."""
    return _fetch_settlements(pid, _recent_business_days()[0].strftime("%m/%d/%Y"))


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


def render_curve() -> None:
    st.caption(
        "Term structure from CME daily settlements (updates after each close). "
        "Contango = back months higher; backwardation = front months higher."
    )
    name = st.selectbox("Symbol", list(CURVE_PRODUCTS.keys()))
    pid = CURVE_PRODUCTS[name]
    if st.button("🔄 Refresh curve"):
        get_curve.clear()
        st.rerun()
    try:
        df = get_curve(pid)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't load curve (CME may be blocking): {str(e)[:80]}")
        return
    if df.empty:
        st.info("No settlement data returned.")
        with st.expander("🔧 Debug: raw CME response"):
            try:
                st.code(get_curve_raw(pid)[:1500])
            except Exception as e:  # noqa: BLE001
                st.write(str(e))
        return

    # chronological order (CME lists many illiquid back years)
    df = df.copy()
    df["_date"] = df["Month"].map(_month_to_date)
    df = df.dropna(subset=["_date"]).sort_values("_date").reset_index(drop=True)

    horizon = st.radio("Horizon", ["12M", "24M", "36M", "All"], index=1,
                       horizontal=True)
    n = {"12M": 12, "24M": 24, "36M": 36, "All": len(df)}[horizon]
    view = df.head(n)

    front, back = view["Settle"].iloc[0], view["Settle"].iloc[-1]
    shape = ("Contango ↗" if back > front else
             "Backwardation ↘" if back < front else "Flat →")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Front ({view['Month'].iloc[0]})", f"{front:,.2f}")
    c2.metric(f"Back ({view['Month'].iloc[-1]})", f"{back:,.2f}")
    c3.metric(shape, f"{back - front:+,.2f}")

    # --- roll / cost of carry ---
    def _months_between(d1, d2):
        return (d2.year - d1.year) * 12 + (d2.month - d1.month)

    if len(view) > 1:
        m1, m2 = view.iloc[0], view.iloc[1]
        roll = m1["Settle"] - m2["Settle"]            # >0 = backwardation
        roll_pct = roll / m2["Settle"] * 100 if m2["Settle"] else 0
        step = _months_between(m1["_date"], m2["_date"]) or 1
        roll_ann = roll_pct * (12 / step)
        span = _months_between(view["_date"].iloc[0], view["_date"].iloc[-1]) or 1
        carry_ann = (front - back) / back * (12 / span) * 100 if back else 0
        d1, d2, d3 = st.columns(3)
        d1.metric(f"Next roll ({m1['Month']}→{m2['Month']})",
                  f"{roll:+,.2f}", f"{roll_pct:+.2f}%")
        d2.metric("Roll annualized", f"{roll_ann:+.1f}%")
        d3.metric(f"Carry annualized (→{view['Month'].iloc[-1]})",
                  f"{carry_ann:+.1f}%")
        st.caption(
            "Positive = backwardation (roll tailwind for longs); "
            "negative = contango (roll drag). Roll = front − 2nd month."
        )

    # --- zoomed chart ---
    lo, hi = view["Settle"].min(), view["Settle"].max()
    pad = max((hi - lo) * 0.15, 0.5)
    chart = (
        alt.Chart(view)
        .mark_line(point=True, color="#14b8a6")
        .encode(
            x=alt.X("_date:T", title="Contract month"),
            y=alt.Y("Settle:Q", title="Settle",
                    scale=alt.Scale(domain=[lo - pad, hi + pad])),
            tooltip=["Month", "Settle"],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, use_container_width=True)
    st.table(view.drop(columns="_date").style.hide(axis="index")
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
