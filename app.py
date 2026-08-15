"""Sakata — the whole terminal, computed on load.

Structure mirrors the static build: this file is the orchestrator, sk_render
holds one function per tab, sk_charts holds the SVG primitives, and sk_ui
holds the palette and helpers. The sk_*.py compute modules are untouched — the
same code that fed build.py feeds this.

Caching replaces the build schedule. Prices and the spread field hold for 15
minutes, matching the shortest bar; Curve, Margins and News hold for an hour
because their sources move once a day and refuse frequent callers.
"""
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st

import sk_amp as AMP
import sk_board as BOARD
import sk_calendar as CAL
import sk_curve as CURVE
import sk_margins as MARGIN
import sk_render as R
import sk_sources as S
import sk_spreads as SP
import sk_technical as TECH
import sk_ui as UI
import sk_universe as U

st.set_page_config(page_title="Sakata · futures terminal", layout="wide",
                   initial_sidebar_state="collapsed")
S.DRY = False
TTL_FAST, TTL_SLOW = 900, 3600

# Bump this after changing anything in sk_margins, sk_spreads, sk_technical or
# sk_sources. st.cache_data hashes only the DECORATED function's own source, so
# editing an imported module leaves every cache here convinced nothing changed
# — which twice looked like a broken feature and was a stale entry. Passing the
# string in as an argument makes the cache key depend on it.
CACHE_V = "2026-08-15d"
DOCS = Path(__file__).parent / "docs" / "data"


def _fallback(name: str):
    """The last committed build, for when a live source refuses. Cheap
    insurance: the static site's JSON is still in the repo."""
    try:
        return json.loads((DOCS / f"{name}.json").read_text(encoding="utf-8"))
    except Exception:
        return None


# ------------------------------------------------------------------ data
@st.cache_data(ttl=TTL_FAST, show_spinner="fetching prices…")
def prices(interval: str, period: str, v: str = CACHE_V) -> dict:
    return S.fetch_ohlc(interval, period)


@st.cache_data(ttl=TTL_FAST)
def by_bar(v: str = CACHE_V) -> dict:
    hourly = prices("1h", "730d")
    daily = prices("1d", "10y")
    return {"1h": hourly,
            "4h": {k: S.resample_4h(v) for k, v in hourly.items()},
            "1d": daily,
            "1wk": {k: S.resample_weekly(v) for k, v in daily.items()}}


@st.cache_data(ttl=TTL_FAST, show_spinner="ranking the field…")
def spread_field(v: str = CACHE_V) -> dict:
    bb = by_bar()
    m15 = prices("15m", "60d")

    def closes(frames):
        return {U.TICKER[c]: df["close"].dropna()
                for c, df in frames.items() if df is not None and len(df)}

    return SP.build_spreads({"15m": closes(m15), "1h": closes(bb["1h"]),
                             "4h": closes(bb["4h"]), "1d": closes(bb["1d"])})


@st.cache_data(ttl=TTL_FAST, show_spinner="reading the ladder…")
def technical_grid(v: str = CACHE_V) -> dict:
    return TECH.build_technical(by_bar())


@st.cache_data(ttl=TTL_SLOW, show_spinner="pulling CME settlements…")
def curve_data(v: str = CACHE_V) -> dict:
    try:
        d = CURVE.build_curve(S.fetch_curves())
    except Exception:
        d = None
    # An empty result is a failed scrape wearing a success costume. Never let
    # it replace a good one.
    return d if (d and d.get("curves")) else (_fallback("curve") or {"curves": {}})


@st.cache_data(ttl=TTL_SLOW, show_spinner="pulling margins…")
def margin_data(v: str = CACHE_V) -> dict:
    """AMP is the fragile half; the vol columns are not.

    If the scrape fails we still recompute everything derived from prices and
    graft the last known maintenance figures onto it, rather than serving a
    whole stale row. Vol and its percentile are then current even on a day the
    scraper is refused, which is the half of the tab that changes daily.

    The reason for a failure is returned alongside the rows. An empty tab that
    says nothing about why cost two rounds of guessing at whether AMP was
    blocked; it was not, the parser had simply stopped matching.
    """
    warn = ""
    try:
        raw, warn = AMP.fetch_amp(S.session())
    except Exception as e:
        raw = {}
        warn = f"{type(e).__name__}: {str(e)[:110]}"
    if not raw:
        old = _fallback("margins") or {"rows": []}
        raw = {r["code"]: {"maint": r.get("maint"), "day": r.get("day")}
               for r in old.get("rows", []) if r.get("maint")}
        warn = (warn or "AMP returned nothing") + " — showing last known "
        warn += "maintenance with live vol"
    d = MARGIN.build_margins(raw, prices("1d", "10y"))
    d["warn"] = warn
    return d


@st.cache_data(ttl=TTL_SLOW, show_spinner="reading the wires…")
def news_data(v: str = CACHE_V) -> dict:
    """Trading Economics, fetched in parallel. Sequential would be fifteen
    pages at up to 25 seconds each; five at a time keeps it under ten."""
    out = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {code: ex.submit(S.fetch_te, url)
                   for code, url in U.TE_PAGE.items()}
        for code, f in futures.items():
            try:
                d = f.result(timeout=40)
            except Exception:
                continue
            if d.get("blurb"):
                out[code] = {"blurb": d["blurb"], "date": d.get("date", "")}
    return out


# ------------------------------------------------------------------ shell
if "dark" not in st.session_state:
    st.session_state.dark = True

UI.apply(st.session_state.dark)

hc = st.columns([16, 1], vertical_alignment="center")
with hc[0]:
    UI.header(dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M") + " UTC · live")
with hc[1]:
    # Anchored so the CSS can lift it onto the tab strip. Theme is the only
    # thing that belongs here now: refresh moved into the tabs, because the
    # sources behind them have nothing to do with each other and refetching
    # fifteen Trading Economics pages to update a margin file is waste.
    UI.md('<div id="sk-theme-anchor"></div>')
    if st.button("☀" if st.session_state.dark else "☾", help="Switch theme"):
        st.session_state.dark = not st.session_state.dark
        st.rerun()


def source(label: str, *caches) -> None:
    """A refresh button, hard left, above whatever controls the tab has.

    The source line that used to sit here is gone. It named where the data
    came from — worth knowing once and clutter every day after — and on the
    tabs that fetch nothing it was a line announcing that there was nothing
    to announce.
    """
    if not caches:
        return
    c = st.columns([1, 9])
    if c[0].button("Refresh", key=f"rf_{label[:24]}", help="Refetch this tab"):
        for fn in caches:
            fn.clear()
        st.rerun()

# Tab order is reading order: what happened, what is being said about it, what
# is scheduled, then the analytical tabs, with the standing reference last.
# Uppercased here rather than in CSS: which element holds the label has moved
# between Streamlit versions, so a selector is a thing that breaks on upgrade.
TABS = ["Board", "News", "Calendar", "Margins", "Technical", "Spreads",
        "Curve", "Knowledge"]
t = st.tabs([x.upper() for x in TABS])

# ----------------------------------------------------------------- Board
with t[0]:
    source("Yahoo · daily closes", prices)
    hz = st.radio("Horizon", R.HZ, horizontal=True, key="board_hz",
                  label_visibility="collapsed")
    daily = prices("1d", "10y")
    if not daily:
        st.error("No daily prices — Yahoo returned nothing.")
    else:
        UI.md(R.board(BOARD.build_board(daily), hz))

# ------------------------------------------------------------------ News
with t[1]:
    source("Trading Economics · per-contract commentary", news_data)
    UI.md(R.news(news_data()))

# -------------------------------------------------------------- Calendar
with t[2]:
    source("Calendar rules and hand-maintained schedules · no fetch")
    cc = st.columns([3, 5])
    sym = cc[0].selectbox("Contract", CAL.symbols(), key="cal_sym",
                          label_visibility="collapsed")
    span = cc[1].radio("Horizon", ["2 weeks", "4 weeks", "8 weeks", "Quarter"],
                       horizontal=True, index=2, key="cal_span",
                       label_visibility="collapsed")
    days = {"2 weeks": 14, "4 weeks": 28, "8 weeks": 56, "Quarter": 92}[span]
    UI.md(R.calendar(CAL.build(days, sym), days, CAL.exhausted()))

# --------------------------------------------------------------- Margins
with t[3]:
    source("AMP margins + CME margin file · Yahoo OHLC for vol", margin_data)
    msort = st.radio("Sort", list(R.MARGIN_SORTS), horizontal=True,
                     key="mg_sort", label_visibility="collapsed")
    UI.md(R.margins(margin_data(), msort))

# ------------------------------------------------------------- Technical
with t[4]:
    source("Yahoo · 1H, 4H, 1D, 1W", technical_grid, prices)
    grid = technical_grid()
    codes = [c for c in U.CODES if c in grid["grid"]]
    if not codes:
        st.error("No technical grid — not enough price history.")
    else:
        cc = st.columns([3, 5])
        code = cc[0].selectbox("Instrument", codes, key="tech_code",
                               format_func=lambda c: f"{c}  {U.NAME[c]}",
                               label_visibility="collapsed")
        avail = [h for h in grid["order"] if h in grid["grid"][code]]
        hzt = cc[1].radio("Horizon", avail, horizontal=True, key="tech_hz",
                          label_visibility="collapsed")
        UI.md(R.technical(grid, code, hzt, U.DEC[code]))

# --------------------------------------------------------------- Spreads
with t[5]:
    source("Yahoo · 15m, 1H, 4H, 1D", spread_field, prices)
    field = spread_field()
    if not field.get("periods"):
        st.error("No spread windows built — not enough price history.")
    else:
        per = st.radio("Window", field["periods"], horizontal=True,
                       key="sp_window", label_visibility="collapsed")
        UI.md(R.spreads(field, per))
        with st.expander("Digest — copy this into an LLM"):
            st.code(R.digest(field["data"][per],
                             dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")),
                    language=None)

# ----------------------------------------------------------------- Curve
with t[6]:
    source("CME settlements", curve_data)
    cd = curve_data()
    codes = list(cd.get("curves", {}))
    if not codes:
        UI.md(R.curve(cd, ""))
    else:
        code = st.selectbox("Contract", codes, key="cv_code",
                            format_func=lambda c: f"{c}  {U.NAME.get(c, c)}",
                            label_visibility="collapsed")
        UI.md(R.curve(cd, code))

# ------------------------------------------------------------- Knowledge
with t[7]:
    source("Hand-maintained in sk_knowledge.py · no fetch")
    grp = st.radio("Group", ["All", "Financials", "Commodities"],
                   horizontal=True, key="kn_group", label_visibility="collapsed")
    UI.md(R.knowledge(grp))
