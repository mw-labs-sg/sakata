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


def _stale() -> list:
    """Imported modules older than the code in this file that calls them.

    Streamlit reruns app.py on every interaction but keeps the modules it
    imported in the same process, so a deploy that changes sk_render can leave
    a new app.py calling an old function. It has surfaced twice: once as
    AttributeError on a constant that did exist, and once as a TypeError about
    keyword arguments that were right there in the source. Both times the
    traceback pointed at the call and said nothing about the cause, and both
    times the fix was to restart the process.

    Checking the signatures of what this file actually calls turns that into a
    sentence with the fix in it. Cheap, and only wrong in the safe direction:
    a missing parameter always means the module is behind.
    """
    import inspect
    want = (("sk_render.portfolio", R.portfolio, ("hold", "turn", "pl")),
            ("sk_render.spreads", R.spreads, ("sort",)),
            ("sk_portfolio.optimise", PF.optimise, ("risk_cap", "progress")),
            ("sk_portfolio.plan", PF.plan, ("margins", "fees", "max_lev")),
            ("sk_portfolio.held_forward", PF.held_forward, ("frac",)),
            ("sk_spreads.build_spreads", SP.build_spreads, ("chart_keys",)),
            ("sk_spreads.window_closes", SP.window_closes, ("by_bar",)),
            ("sk_ui.note", UI.note, ("wide",)))
    behind = []
    for name, fn, params in want:
        try:
            have = set(inspect.signature(fn).parameters)
        except (TypeError, ValueError):        # builtins, C functions
            continue
        missing = [x for x in params if x not in have]
        if missing:
            behind.append(f"{name} has no {', '.join(missing)}")
    return behind


_behind = _stale()
if _behind:
    st.error("Sakata is running stale modules, so this page is newer than the "
             "code it is calling: " + "; ".join(_behind) + ". Nothing is "
             "wrong with the data — the process needs restarting. On "
             "Streamlit Cloud: Manage app → Reboot. Locally: stop and rerun "
             "`streamlit run app.py`.")
    st.stop()

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

CAPITAL_MIN, CAPITAL_MAX = 1_000, 1_000_000_000


def _maint() -> dict:
    """{code: maintenance margin} off the Margins tab's own cached pull.

    Same numbers, one source. A portfolio tab that scraped its own margins
    would eventually disagree with the tab whose whole job is margins.
    """
    try:
        return {r["code"]: r["maint"] for r in margin_data().get("rows", [])
                if r.get("maint")}
    except Exception:
        return {}


def _dollars(text: str) -> int:
    """Digits out of whatever was typed, clamped to something sizeable.

    A text box rather than st.number_input because number_input cannot group
    thousands — its format string is printf, which has no separator flag — and
    1000000 is a number you have to count digits on.
    """
    digits = "".join(c for c in str(text) if c.isdigit())
    return max(CAPITAL_MIN, min(int(digits or CAPITAL_MIN), CAPITAL_MAX))


def _capital() -> None:
    """Rewrite the box with separators, on change. Runs as a callback, which
    is the only point at which a widget's own state may still be set."""
    st.session_state["pf_capital_txt"] = f"{_dollars(st.session_state.get('pf_capital_txt', '')):,}"


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


def portfolio_weights(window: str, objective: str, legs: int, cap: int,
                      side: str, risk_cap: float = 0.0,
                      progress=None) -> dict:
    """One search. NOT cached, deliberately.

    It was, until the progress bar arrived: `progress` calls st.progress from
    inside the search, st.cache_data records every st.* call made inside a
    cached function so it can replay them on a hit, and a replay cannot
    reconstruct the closure that bar lives in. On Streamlit Cloud that landed
    as CacheReplayClosureError the second time the button was pressed with the
    same settings. A cached function cannot draw, so this one is not cached.

    Nothing is lost by that. The search only runs on an explicit press, the
    answer is held in session state for the sizing to read, and the window
    data it works from is cached in portfolio_frames — which is the expensive,
    shared part.
    """
    closes, fine = portfolio_frames(window)
    if closes is None:
        return {}
    return PF.optimise(closes, fine, objective, max_legs=legs,
                       max_weight=cap / 100, side=side,
                       risk_cap=risk_cap, progress=progress)


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
    # Optimize sits on the header line with Refresh: both are "go and do
    # something", and it was the only control on the tab that did not belong
    # with the settings it followed.
    go = source("Yahoo · 15m, 1H, 4H, 1D", *PRICE_CACHES, key="portfolio",
                action="Optimize")
    # Two rows of five, equal widths, every control the same shape of box.
    # The Shorts checkbox used to sit mid-row with no box around it, which
    # pulled its label half a line up and left the rows out of register. A
    # direction belongs in a dropdown anyway: long-and-short, long-only and
    # short-only are three answers, not a yes and a no.
    r1 = st.columns(5)
    pf_win = r1[0].selectbox("Time frame", PF_WINDOWS, key="pf_window")
    pf_legs = r1[1].selectbox("Max legs", list(range(2, 11)), index=4,
                              key="pf_legs")
    pf_cap = r1[2].selectbox("Weight cap", ["25%", "35%", "50%", "100%"],
                             index=2, key="pf_cap",
                             help="Most any one instrument may carry. The cap "
                                  "and the leg count are the only defence "
                                  "against a search fitting one window.")
    pf_risk = r1[3].selectbox("Risk cap", ["none", "60%", "50%", "40%", "30%"],
                              key="pf_risk",
                              help="Most of the portfolio's VARIANCE any one"
                                   " leg may carry. The weight cap limits the"
                                   " money in a leg; this limits the risk,"
                                   " which is a different thing — a basket can"
                                   " hold a tenth of its money in ether and"
                                   " half its variance there.")
    pf_side = r1[4].selectbox("Direction", PF.SIDES, key="pf_side",
                              help="Which way the legs may point. Long only"
                                   " and short only are one-sided books; long"
                                   " and short lets the search hedge.")

    r2 = st.columns(5)
    pf_obj = r2[0].selectbox("Objective", PF.OBJECTIVES, key="pf_obj",
                             help="What the search maximises. ROA and ER (Adj)"
                                  " depend on the order of the returns, so"
                                  " weights are searched, not solved.")
    # Capital, vol target and leverage are not search arguments: the weights
    # are a shape and these only decide how large it is drawn, so they take
    # effect without a re-run.
    pf_cap_usd = _dollars(r2[1].text_input(
        "Capital", value="1,000,000", key="pf_capital_txt", on_change=_capital,
        help="What the weights are sized against. Notional and contracts scale"
             " with it; the ratios do not. Below about $500k these baskets"
             " stop being fillable — watch the Miss column."))
    pf_vol = r2[2].selectbox("Vol target",
                             ["5%", "10%", "15%", "20%", "30%", "none"],
                             index=4, key="pf_vol",
                             help="Annualised volatility to hold the basket"
                                  " at; leverage is this over the portfolio's"
                                  " own volatility, so a noisy basket is held"
                                  " below 1×. Pick none to size on leverage"
                                  " instead and hold the cap.")
    pf_lev = r2[3].selectbox("Max leverage", ["1×", "2×", "3×", "5×", "none"],
                             index=0, key="pf_lev",
                             help="Ceiling on gross notional over capital. A"
                                  " quiet basket needs leverage to reach a vol"
                                  " target; this is where you say how much of"
                                  " that you will actually take.")
    pf_fee = r2[4].selectbox("Fees", list(U.FEE_TIERS), key="pf_fee",
                             help="Round-turn commission per contract, scaled"
                                  " from a retail schedule. It decides between"
                                  " fills that are equally close to the"
                                  " target, so it changes the tickets rather"
                                  " than the weights.")

    r3 = st.columns(5)
    pf_size = r3[0].selectbox("Contracts",
                              ["Standard + small", "Standard only"],
                              key="pf_size",
                              help="Whether micros and minis may be used to"
                                   " close the gap on a leg. Standard only is"
                                   " fewer tickets and cheaper commission, at"
                                   " the price of a coarser fill — watch the"
                                   " Miss column when you switch.")

    pf_args = (pf_win, pf_obj, pf_legs, pf_cap, pf_side, pf_risk)
    if go:
        # A bar rather than a spinner: the search runs tens of seconds now
        # that it restarts, grows and swaps legs, and a spinner that long
        # reads as a hang. The running best is on it, which also shows the
        # thing worth watching — how early it stops improving.
        bar = st.progress(0.0, text="searching weights…")

        def _tick(done, total, best):
            got = "" if best is None else f" · best {best:,.1f}"
            bar.progress(min(done / max(total, 1), 1.0),
                         text=f"searching weights… {done}/{total}{got}")

        rc = 0.0 if pf_risk == "none" else int(pf_risk.rstrip("%")) / 100
        fresh_res = portfolio_weights(
            pf_win, pf_obj, pf_legs, int(pf_cap.rstrip("%")), pf_side,
            risk_cap=rc, progress=_tick)
        # Turnover against the PREVIOUS answer, captured before it is
        # overwritten. For a book tracked through a week, "is it still saying
        # the same thing" is a more useful question than any single ROA.
        st.session_state["pf_turn"] = PF.turnover(
            fresh_res.get("weights") if fresh_res else None,
            (st.session_state.get("pf_result") or {}).get("weights"))
        st.session_state["pf_result"] = fresh_res
        st.session_state["pf_for"] = pf_args

        bar.progress(0.0, text="holding the fit forward…")
        closes_h, fine_h = portfolio_frames(pf_win)
        st.session_state["pf_hold"] = PF.held_forward(
            closes_h, fine_h, pf_obj, max_legs=pf_legs,
            max_weight=int(pf_cap.rstrip("%")) / 100, side=pf_side,
            risk_cap=rc,
            progress=lambda d, t, b: bar.progress(
                min(d / max(t, 1), 1.0),
                text=f"holding the fit forward… {d}/{t}"))
        bar.empty()
    res = st.session_state.get("pf_result")
    if res and st.session_state.get("pf_for") != pf_args:
        st.caption("Controls changed since this ran — press Optimize again.")
    # Priced off the same cached daily closes as the Board and the contract
    # specs on Knowledge, so three tabs cannot disagree about what one
    # contract costs.
    last_pf = {c: float(df["close"].iloc[-1])
               for c, df in prices("1d", "10y").items()
               if df is not None and len(df)}
    shown_win = st.session_state.get("pf_for", pf_args)[0]
    plan, hold = {}, None
    if res:
        closes_pf, fine_pf = portfolio_frames(shown_win)
        if closes_pf is not None:
            plan = PF.plan(closes_pf, fine_pf, res, pf_cap_usd,
                           None if pf_vol == "none"
                           else float(pf_vol.rstrip("%")),
                           last_pf, U.MULT, U.MICRO,
                           max_lev=(None if pf_lev == "none"
                                    else float(pf_lev.rstrip("×"))),
                           fees=U.FEES, fee_tier=U.FEE_TIERS[pf_fee],
                           margins=_maint(),
                           smalls=(pf_size == "Standard + small"))
            # Requoted at the leverage on screen, so the held-forward row is
            # in the same units as the three above it. Cheap — one scorer over
            # the tail of the window — and it has to happen here rather than
            # in the search, because capital and vol target move afterwards.
            hold = st.session_state.get("pf_hold")
            if hold and hold.get("w"):
                hold = dict(hold, stats=PF.hold_stats(
                    closes_pf, fine_pf, hold["w"], plan.get("lev", 1.0)))
    # Held forward and turnover belong to the run that produced them. Showing
    # yesterday's holdout beside today's window would be the tab quietly
    # answering a question about a different portfolio.
    same = st.session_state.get("pf_for") == pf_args
    UI.md(R.portfolio(res or {}, shown_win, plan, capital=pf_cap_usd,
                      vol_target=(None if pf_vol == "none"
                                  else float(pf_vol.rstrip("%"))),
                      hold=hold if same else None,
                      turn=st.session_state.get("pf_turn") if same else None))


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
