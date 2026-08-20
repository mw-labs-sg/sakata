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
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Before the sk_* imports, not after: sk_render uses PEP 701 f-strings, so on
# 3.11 it fails at COMPILE time and the traceback points at a quote rather than
# at the version. Checking here turns that into a sentence.
if sys.version_info < (3, 12):
    raise SystemExit(
        "Sakata needs Python 3.12+ (sk_render.py uses PEP 701 f-strings); "
        f"this interpreter is {sys.version.split()[0]}.")

import streamlit as st

import sk_amp as AMP
import sk_board as BOARD
import sk_calendar as CAL
import sk_curve as CURVE
import sk_margins as MARGIN
import sk_portfolio as PF
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

# st.cache_data hashes only the DECORATED function's own source, so editing an
# imported module leaves every cache here convinced nothing changed — which
# twice looked like a broken feature and was a stale entry. Passing a version
# string in as an argument makes the key depend on it.
#
# That string used to be bumped by hand, which is a rule you obey until the one
# time you don't: it read 2026-08-15f while a dozen edits to the compute modules
# had landed underneath it. Hashing their source instead means the caches
# invalidate exactly when the code that fills them changes, and never otherwise.
def _cache_key() -> str:
    import hashlib
    h = hashlib.sha256()
    here = Path(__file__).parent
    for name in ("sakata_stats", "sk_amp", "sk_board", "sk_calendar",
                 "sk_curve", "sk_fmt", "sk_margins", "sk_sources",
                 "sk_spreads", "sk_technical", "sk_universe"):
        try:
            h.update((here / f"{name}.py").read_bytes())
        except OSError:      # a module gone missing is its own kind of change
            h.update(name.encode())
    return h.hexdigest()[:12]


CACHE_V = _cache_key()
DOCS = Path(__file__).parent / "docs" / "data"


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


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


def _closes(frames: dict) -> dict:
    """{code: OHLC frame} to {ticker: close series}, the shape sk_spreads
    slices windows out of."""
    return {U.TICKER[c]: df["close"].dropna()
            for c, df in frames.items() if df is not None and len(df)}


def _by_bar_closes() -> dict:
    """Every bar size the windows can be built from, closes only."""
    bb = by_bar()
    return {"15m": _closes(prices("15m", "60d")), "1h": _closes(bb["1h"]),
            "4h": _closes(bb["4h"]), "1d": _closes(bb["1d"])}


PF_WINDOWS = ["Intraday", "WTD", "MTD", "QTD", "YTD", "30D", "60D",
              "120D", "240D"]


@st.cache_data(ttl=TTL_FAST, show_spinner=False)
def portfolio_frames(window: str, v: str = CACHE_V):
    """(closes, fine) for one window — the search and the sizing both need
    them, and neither should slice its own."""
    bb = _by_bar_closes()
    closes, _dropped = SP.window_closes(window, bb)
    if closes is None:
        return None, None
    fine, _bar = SP.fine_closes(window, bb, closes)
    return closes, fine


@st.cache_data(ttl=TTL_FAST, show_spinner=False)
def portfolio_weights(window: str, objective: str, legs: int, cap: int,
                      shorts: bool, v: str = CACHE_V) -> dict:
    """One search, cached on its arguments so re-pressing the button is free.

    Reads the same aligned window the field is built from rather than slicing
    its own: two answers about "the last 30 days" that disagree on which days
    those were is the bug this avoids.
    """
    closes, fine = portfolio_frames(window)
    if closes is None:
        return {}
    return PF.optimise(closes, fine, objective, max_legs=legs,
                       max_weight=cap / 100, allow_short=shorts)


@st.cache_data(ttl=TTL_FAST, show_spinner="ranking the field…")
def spread_field(mode: str = "vol", v: str = CACHE_V) -> dict:
    """`mode` is a cache key, not a display flag: it selects the return series
    the whole field is computed from, so each basis gets its own entry."""
    out = SP.build_spreads(_by_bar_closes(),
                           mode=mode,
                           # Every ranking the Function picker offers, so the
                           # chart grid can follow the table into any of them
                           # without a rebuild. The site build asks for none of
                           # this and keeps its single default grid.
                           chart_keys=tuple(R.SORTS.values()))
    # Stamped INSIDE the cached function, so it records when the field was
    # actually built rather than when the page happened to render. A browser
    # reload reruns the script but returns this same entry untouched, which is
    # why the numbers can look frozen: they are, until the TTL lapses.
    out["computed"] = dt.datetime.now(dt.timezone.utc)
    return out


@st.cache_data(ttl=TTL_FAST, show_spinner="reading the ladder…")
def technical_grid(v: str = CACHE_V) -> dict:
    return TECH.build_technical(by_bar())


@st.cache_data(ttl=TTL_SLOW, show_spinner="pulling CME settlements…")
def curve_data(v: str = CACHE_V) -> dict:
    """The reason for a failure travels with the data, as it does for margins.

    A bare `except: d = None` said nothing about why, and a PARTIAL scrape said
    nothing at all: live, eleven of sixteen products came back and the tab
    reported that as success, with ZB, ZN, ZC, ZW and ZS simply absent.
    """
    warn = ""
    try:
        d = CURVE.build_curve(S.fetch_curves())
    except Exception as e:
        d, warn = None, f"{type(e).__name__}: {str(e)[:110]}"
    # An empty result is a failed scrape wearing a success costume. Never let
    # it replace a good one.
    if d and d.get("curves"):
        missing = [c for c in U.CME_PRODUCT if c not in d["curves"]]
        if missing:
            warn = (f"{len(d['curves'])}/{len(U.CME_PRODUCT)} products returned "
                    f"— no curve for {', '.join(missing)}")
    else:
        d = _fallback("curve") or {"curves": {}}
        warn = (warn or "CME returned nothing") + " — showing the last build"
    d["warn"] = warn
    return d


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
    out, failed = {}, []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {code: ex.submit(S.fetch_te, url, code)
                   for code, url in U.TE_PAGE.items()}
        for code, f in futures.items():
            try:
                d = f.result(timeout=40)
            except Exception as e:
                failed.append(f"{code} ({type(e).__name__})")
                continue
            if d.get("blurb"):
                out[code] = {"blurb": d["blurb"], "date": d.get("date", ""),
                             "headline": d.get("headline", ""),
                             "onTopic": d.get("onTopic", True)}
            else:
                failed.append(code + (f" ({d['err']})" if d.get("err") else ""))
    # Which pages came back empty, rather than a silently shorter tab.
    return {"markets": out,
            "warn": (f"no commentary parsed for {', '.join(failed)}"
                     if failed else "")}


# Every price-derived tab clears the same group. They all descend from one
# Yahoo fetch, so clearing a subset left them disagreeing about the same
# instrument at the same moment: refreshing Board dropped `prices` but left
# `by_bar` holding the older frames, so Board showed the new close while
# Spreads and Technical still ranked the old one — and Spreads' own refresh
# rebuilt the field without touching technical_grid.
#
# News, Margins and Curve stay out of it deliberately. They hit slower sources
# that rate-limit, and re-scraping AMP because a price tab was refreshed is the
# waste the per-tab button existed to avoid.
PRICE_CACHES = (prices, by_bar, spread_field, technical_grid)


# ------------------------------------------------------------------ shell
if "dark" not in st.session_state:
    st.session_state.dark = True

UI.apply(st.session_state.dark)

hc = st.columns([16, 1], vertical_alignment="center")
with hc[0]:
    UI.header(_utc() + " UTC · live")
with hc[1]:
    # Anchored so the CSS can lift it onto the tab strip. Theme is the only
    # thing that belongs here now: refresh moved into the tabs, because the
    # sources behind them have nothing to do with each other and refetching
    # fifteen Trading Economics pages to update a margin file is waste.
    UI.md('<div id="sk-theme-anchor"></div>')
    if st.button("☀" if st.session_state.dark else "☾", help="Switch theme"):
        st.session_state.dark = not st.session_state.dark
        st.rerun()


@st.fragment(run_every=20)
def autorefresh(stamp, ttl: int) -> None:
    """Pull the tab through when its data has actually expired.

    A blind timer would rerun the app every N seconds and mostly redraw
    identical numbers, because st.cache_data hands back the same entry until
    the TTL lapses — which is exactly why a browser reload appears to do
    nothing. This watches the clock instead and reruns only once the entry is
    genuinely stale, so the refetch happens on the first tick after expiry
    rather than on the next time someone remembers to press the button.

    The fragment reruns itself cheaply; scope="app" is what pulls the whole
    script through, and only then.
    """
    if not stamp:
        return
    if (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds() >= ttl:
        st.rerun(scope="app")


def source(label: str, *caches, key: str = "", action: str = "") -> bool:
    """A refresh button, hard left, above whatever controls the tab has.

    The source line that used to sit here is gone. It named where the data
    came from — worth knowing once and clutter every day after — and on the
    tabs that fetch nothing it was a line announcing that there was nothing
    to announce.

    `action` puts a second button beside Refresh and returns whether it was
    pressed. Both are "go and do something", which is a different kind of
    control from the selectors underneath and belongs on its own line.
    """
    if not caches:
        return False
    c = st.columns([1, 1, 8] if action else [1, 9])
    # Keyed on the tab, not on a slice of the source line: two tabs whose
    # prose happened to share 24 characters would have collided into a
    # DuplicateWidgetID at import time.
    if c[0].button("Refresh", key=f"rf_{key or label[:24]}",
                   help="Refetch this tab"):
        for fn in caches:
            fn.clear()
        st.rerun()
    return bool(action) and c[1].button(action, key=f"go_{key}",
                                        type="primary")

# Tab order is reading order: what happened, what is being said about it, what
# is scheduled, then the analytical tabs, with the standing reference last.
# Uppercased here rather than in CSS: which element holds the label has moved
# between Streamlit versions, so a selector is a thing that breaks on upgrade.
TABS = ["Board", "News", "Calendar", "Margins", "Technical", "Trends",
        "Portfolio", "Curve", "Knowledge"]
t = st.tabs([x.upper() for x in TABS])

# ----------------------------------------------------------------- Board
with t[0]:
    source("Yahoo · daily closes", *PRICE_CACHES, key="board")
    hz = st.radio("Horizon", R.HZ, horizontal=True, key="board_hz",
                  label_visibility="collapsed")
    daily = prices("1d", "10y")
    if not daily:
        st.error("No daily prices — Yahoo returned nothing.")
    else:
        UI.md(R.board(BOARD.build_board(daily), hz))

# ------------------------------------------------------------------ News
with t[1]:
    source("Trading Economics · per-contract commentary", news_data, key="news")
    nd = news_data()
    UI.md(R.news(nd.get("markets", {}), nd.get("warn", "")))

# -------------------------------------------------------------- Calendar
with t[2]:
    # No refresh button: nothing here is fetched. Every row is either a
    # calendar rule evaluated at render time or a hand-maintained date, so
    # the tab is already as current as it can be. No symbol filter either —
    # the Symbol column is scannable and a dropdown to hide rows on a
    # two-week view removed more than it added.
    span = st.radio("Horizon", ["2 weeks", "4 weeks", "8 weeks", "Quarter"],
                    horizontal=True, index=0, key="cal_span",
                    label_visibility="collapsed")
    days = {"2 weeks": 14, "4 weeks": 28, "8 weeks": 56, "Quarter": 92}[span]
    UI.md(R.calendar(CAL.build(days), days, CAL.exhausted()))

# --------------------------------------------------------------- Margins
with t[3]:
    source("AMP margins + CME margin file · Yahoo OHLC for vol", margin_data, key="margins")
    msort = st.radio("Sort", list(R.MARGIN_SORTS), horizontal=True,
                     key="mg_sort", label_visibility="collapsed")
    UI.md(R.margins(margin_data(), msort))

# ------------------------------------------------------------- Technical
with t[4]:
    # by_bar belongs in this list. Without it, clearing technical_grid and
    # prices left by_bar's 15-minute entry intact, so the grid was rebuilt from
    # byte-identical bars and Refresh fetched nothing — while Board's Refresh
    # DID clear prices, so the two tabs could then read different fetches of the
    # same daily series.
    source("Yahoo · 1H, 4H, 1D, 1W", *PRICE_CACHES, key="technical")
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
    source("Yahoo · 15m, 1H, 4H, 1D", *PRICE_CACHES, key="spreads")
    # Basis is read BEFORE the field is built, because it decides what gets
    # built. Writing into sc[2] first still lands it in the third column —
    # st.columns places by container, not by call order — so the controls read
    # left to right while the dependency runs the other way.
    # Dropdowns, not radios: nine options across three groups wrapped onto two
    # ragged lines and read as clutter above a dense table. Sizing is read
    # first because it decides what gets built; st.columns places by container,
    # so the controls still sit left to right.
    sc = st.columns([3, 3, 3, 2])
    basis = sc[2].selectbox("Sizing type", list(R.BASES), key="sp_basis",
                            help="Vol equalises dollar risk (n × notional × σ);"
                                 " notional equalises dollar exposure. Sets the"
                                 " weighting the field is ranked on and the"
                                 " contract ratio shown in Size.")
    field = spread_field(R.BASES[basis])
    if not field.get("periods"):
        st.error("No spread windows built — not enough price history.")
    else:
        stamp = field.get("computed")
        per = sc[0].selectbox("Time frame", field["periods"], key="sp_window")
        spsort = sc[1].selectbox("Function", list(R.SORTS), key="sp_sort")
        sc[3].checkbox("Auto", key="sp_auto",
                       help="Refetch by itself once the 15-minute cache "
                            "expires, instead of waiting for Refresh")
        UI.md(R.spreads(field, per, spsort, R.freshness(stamp, TTL_FAST)))
        if st.session_state.get("sp_auto"):
            autorefresh(stamp, TTL_FAST)
        with st.expander("Digest — copy this into an LLM"):
            st.code(R.digest(field["data"][per], _utc()), language=None)

# ------------------------------------------------------------- Portfolio
with t[6]:
    # Optimise sits on the header line with Refresh: both are "go and do
    # something", and it was the only control on the tab that did not belong
    # with the settings it followed.
    go = source("Yahoo · 15m, 1H, 4H, 1D", *PRICE_CACHES, key="portfolio",
                action="Optimise")
    pc = st.columns([3, 3, 2, 2, 2])
    pf_win = pc[0].selectbox("Time frame", PF_WINDOWS, key="pf_window")
    pf_obj = pc[1].selectbox("Objective", PF.OBJECTIVES, key="pf_obj",
                             help="What the search maximises. ROA and ER (Adj)"
                                  " depend on the order of the returns, so"
                                  " weights are searched, not solved.")
    pf_legs = pc[2].selectbox("Max legs", list(range(2, 11)), index=4,
                              key="pf_legs")
    pf_cap = pc[3].selectbox("Weight cap", ["25%", "35%", "50%", "100%"],
                             index=2, key="pf_cap",
                             help="Most any one instrument may carry. The cap "
                                  "and the leg count are the only defence "
                                  "against a search fitting one window.")
    pf_short = pc[4].checkbox("Shorts", value=True, key="pf_short",
                              help="Allow negative weights. Off makes it a "
                                   "long-only basket.")
    # Capital and vol target sit on their own row because they are not search
    # arguments: the weights are a shape, and these two only decide how large
    # it is drawn. They take effect immediately, without a re-run.
    sc2 = st.columns([3, 2, 2, 2, 3])
    pf_cap_usd = sc2[0].number_input("Capital", min_value=1_000,
                                     max_value=1_000_000_000,
                                     value=1_000_000,
                                     step=100_000, key="pf_capital",
                                     help="What the weights are sized against."
                                          " Notional and contracts scale with"
                                          " it; the ratios do not. Below about"
                                          " $500k these baskets stop being"
                                          " fillable — watch the Miss column.")
    pf_vol = sc2[1].selectbox("Vol target",
                              ["5%", "10%", "15%", "20%", "30%", "none"],
                              index=4, key="pf_vol",
                              help="Annualised volatility to hold the basket"
                                   " at; leverage is this over the portfolio's"
                                   " own volatility, so a noisy basket is held"
                                   " below 1×. Pick none to size on leverage"
                                   " instead and hold the cap.")
    pf_fee = sc2[3].selectbox("Fees", list(U.FEE_TIERS), key="pf_fee",
                              help="Round-turn commission per contract,"
                                   " scaled from a retail schedule. It decides"
                                   " between fills that are equally close to"
                                   " the target, so it changes the tickets"
                                   " rather than the weights.")
    pf_lev = sc2[2].selectbox("Max leverage", ["1×", "2×", "3×", "5×", "none"],
                              index=0, key="pf_lev",
                              help="Ceiling on gross notional over capital. A"
                                   " quiet basket needs leverage to reach a"
                                   " vol target; this is where you say how"
                                   " much of that you will actually take.")
    # Behind a button on purpose: st.tabs runs every tab body on every rerun,
    # so an optimiser called at the top level would charge a search to anyone
    # who touched a radio on Board.
    pf_args = (pf_win, pf_obj, pf_legs, pf_cap, pf_short)
    if go:
        with st.spinner("searching weights…"):
            st.session_state["pf_result"] = portfolio_weights(
                pf_win, pf_obj, pf_legs, int(pf_cap.rstrip("%")), pf_short)
            st.session_state["pf_for"] = pf_args
    res = st.session_state.get("pf_result")
    if res and st.session_state.get("pf_for") != pf_args:
        st.caption("Controls changed since this ran — press Optimise again.")
    # Priced off the same cached daily closes as the Board and the contract
    # specs on Knowledge, so three tabs cannot disagree about what one
    # contract costs.
    last_pf = {c: float(df["close"].iloc[-1])
               for c, df in prices("1d", "10y").items()
               if df is not None and len(df)}
    shown_win = st.session_state.get("pf_for", pf_args)[0]
    plan = {}
    if res:
        closes_pf, fine_pf = portfolio_frames(shown_win)
        if closes_pf is not None:
            plan = PF.plan(closes_pf, fine_pf, res, pf_cap_usd,
                           None if pf_vol == "none"
                           else float(pf_vol.rstrip("%")),
                           last_pf, U.MULT, U.MICRO,
                           max_lev=(None if pf_lev == "none"
                                    else float(pf_lev.rstrip("×"))),
                           fees=U.FEES, fee_tier=U.FEE_TIERS[pf_fee])
    UI.md(R.portfolio(res or {}, shown_win, plan, capital=pf_cap_usd,
                      vol_target=(None if pf_vol == "none"
                                  else float(pf_vol.rstrip("%")))))


# ----------------------------------------------------------------- Curve
with t[7]:
    source("CME settlements", curve_data, key="curve")
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
with t[8]:
    source("Hand-maintained in sk_knowledge.py · no fetch")
    grp = st.radio("Group", ["All", "Financials", "Commodities"],
                   horizontal=True, key="kn_group", label_visibility="collapsed")
    # Priced off the same cached daily closes the Board reads, so the
    # notionals on this tab and the prices on that one cannot disagree.
    daily_kn = prices("1d", "10y")
    last_kn = {c: float(df["close"].iloc[-1]) for c, df in daily_kn.items()
               if df is not None and len(df)}
    UI.md(R.knowledge(grp, last_kn))
