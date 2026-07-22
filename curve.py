"""Curve tab — futures term structure from CME/ICE settlements."""
import datetime as _d

import altair as alt
import pandas as pd
import streamlit as st

from common import _session


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
