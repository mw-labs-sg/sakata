"""Sakata — the spread field, one ranked table and a chart set per window.

Nine windows, not four. The calendar periods answer "how is this quarter
going"; the rolling ones answer "what has worked lately", and those are
different questions that disagree often enough to be worth seeing side by
side. A pair that tops 30D, 60D AND 120D is a different object from one that
only tops the shortest.

Every window is sliced from bars already fetched — nothing here goes to the
network. The chart series ship with the field so the page can show WHY a row
ranked, which no column in the table can: a spread whose Sharpe came from one
leg collapsing looks nothing like one where both legs trended and the gap
widened.
"""
import datetime as dt
from collections import OrderedDict

import numpy as np
import pandas as pd

import sakata_stats as ss
import sk_universe as U

MODE = "vol"            # vol-adjusted legs; equal notional lets the loud leg win
RATIO_CAP = 5.0         # above this the sizing is not executable
TOP_N = 30              # rows in the table
CHART_N = 12            # candidates that ship a chart series
CHART_PTS = 160         # points per line after decimation
MAX_LEG_CHARTS = 2      # times one instrument may appear across those charts
# Below this a window is SHORT, and gets said so — but it still ranks. The
# floor used to suppress the table outright; a 19-bar WTD then rendered as a
# refusal on a Monday, which is exactly when you want to look at it. ER is
# descriptive rather than an estimate of a forward parameter, so it survives a
# short sample better than Sharpe does; the bar count rides along so the reader
# can discount it themselves.
MIN_DISPLAY_BARS = 20

# Windows offered in the selector. The rolling ones keep computing because the
# "also top-10 in" column is only worth reading if it spans more than the five
# calendar windows — but nine radio buttons over one table was the tab's worst
# habit, so they no longer appear in the picker.
DISPLAY_PERIODS = ["Intraday", "WTD", "MTD", "QTD", "YTD"]

# Point sakata_stats at the live universe so anything added later flows through
# without editing two files.
ss.ALL_SYMBOLS = list(U.TICKERS)
ss.SYMBOL_NAMES = {U.TICKER[c]: c for c in U.CODES}
ss.SYMBOL_SECTOR = {U.TICKER[c]: U.SECTOR[c] for c in U.CODES}

# Bar size per window is chosen so each lands in roughly 60-400 bars. Too few
# and every statistic is noise; too many and an hourly series over a year is a
# daily series with six times the payload and none of the extra information.
WINDOWS = OrderedDict([
    # NOT "last 3 sessions". The slice is 3 calendar days, and align_frames
    # then inner-joins 19 markets, so what survives is only the hours when all
    # of them trade at once — measured, 61 bars over 3 days, about 5 hours a
    # day rather than 3 full sessions. The join is deliberate (see
    # align_frames) so the label is what changes.
    ("Intraday", dict(bar="15m", kind="days",  n=3,   note="15-minute bars, last 3 days, hours all 19 markets trade")),
    ("WTD",      dict(bar="1h",  kind="cal",   unit="week",    note="hourly bars since Monday")),
    ("MTD",      dict(bar="4h",  kind="cal",   unit="month",   note="4-hour bars since the 1st")),
    ("QTD",      dict(bar="1d",  kind="cal",   unit="quarter", note="daily bars since quarter start")),
    ("YTD",      dict(bar="1d",  kind="cal",   unit="year",    note="daily bars since 1 January")),
    ("30D",      dict(bar="1d",  kind="bars",  n=30,  note="last 30 trading days")),
    ("60D",      dict(bar="1d",  kind="bars",  n=60,  note="last 60 trading days")),
    ("120D",     dict(bar="1d",  kind="bars",  n=120, note="last 120 trading days")),
    ("240D",     dict(bar="1d",  kind="bars",  n=240, note="last 240 trading days")),
])
PERIODS = list(WINDOWS)
INTRADAY_BARS = {"15m", "1h", "4h"}


# ------------------------------------------------------------------ slicing
def _cal_start(unit, now=None):
    now = (now or dt.datetime.now()).replace(hour=0, minute=0, second=0,
                                             microsecond=0)
    if unit == "week":
        return now - dt.timedelta(days=now.weekday())
    if unit == "month":
        return now.replace(day=1)
    if unit == "quarter":
        return now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1)
    return now.replace(month=1, day=1)


def _slice(frames, spec):
    """Calendar windows cut by date, rolling windows by bar count. A '30D'
    that quietly became 22 because of holidays is a lie with a label on it."""
    if spec["kind"] == "cal":
        start = pd.Timestamp(_cal_start(spec["unit"]))
        return {k: v[v.index >= start] for k, v in frames.items()}
    if spec["kind"] == "days":
        live = [v for v in frames.values() if len(v)]
        if not live:
            return {}
        last = max(v.index[-1] for v in live)
        start = last.normalize() - pd.Timedelta(days=spec["n"])
        return {k: v[v.index >= start] for k, v in frames.items()}
    return {k: v.tail(spec["n"]) for k, v in frames.items()}


def _num(v, n=2):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, n)


def _sig(v, digits=5):
    """Significant figures, not fixed decimals — the same rounding ships
    useful precision on a 0.0062 yen series and on a 63,000 bitcoin one."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else float(f"{f:.{digits}g}")


def _thin(s, n=CHART_PTS):
    """Decimate to at most n points. A 240-bar line drawn 300px wide cannot
    show 240 points anyway, and the payload is the whole cost of the tab."""
    if len(s) <= n:
        return s
    step = int(np.ceil(len(s) / n))
    out = s.iloc[::step]
    if out.index[-1] != s.index[-1]:
        out = pd.concat([out, s.iloc[-1:]])
    return out


def _curves(cand, data, mode):
    """The three lines: each leg rebased, and the spread itself.

    The spread is rebuilt from returns rather than plotted as a difference of
    the two rebased legs, because that difference IS an equal-notional spread
    and would contradict the vol-adjusted weighting the table ranked on.
    """
    lg, sh = cand.get("long"), cand.get("short")
    if lg and sh:
        r1 = data[lg].pct_change().dropna()
        r2 = data[sh].pct_change().dropna()
        sp, _ = ss.weighted_spread(r1, r2, mode)
        long_line, short_line = data[lg], data[sh]
    else:
        sym = lg or sh
        r = data[sym].pct_change().dropna()
        sp = r if lg else -r
        long_line = data[sym] if lg else None
        short_line = data[sym] if sh else None
    spread = 100 * (1 + sp).cumprod()
    spread = pd.concat([pd.Series([100.0], index=data.index[:1]), spread])
    spread = spread[~spread.index.duplicated(keep="last")]

    idx = _thin(spread).index
    fmt = "%d %b %H:%M" if len(data) and (data.index[-1] - data.index[0]).days < 20 \
        else "%d %b"
    return {
        "t": [d.strftime(fmt) for d in idx],
        "sp": [_sig(v) for v in spread.reindex(idx).values],
        "lg": ([_sig(v) for v in long_line.reindex(idx).values]
               if long_line is not None else None),
        "sh": ([_sig(v) for v in short_line.reindex(idx).values]
               if short_line is not None else None),
        "lgName": ss.name_of(lg) if lg else None,
        "shName": ss.name_of(sh) if sh else None,
    }


# ------------------------------------------------------------------ compute
def _window_field(name, by_bar):
    spec = WINDOWS[name]
    frames = by_bar.get(spec["bar"])
    if not frames:
        return None
    frames = _slice(frames, spec)
    frames = {k: v for k, v in frames.items() if len(v) >= 5}
    if len(frames) < 2:
        return None

    data, dropped, _cov = ss.align_frames(
        frames, intraday=spec["bar"] in INTRADAY_BARS)
    if data is None:
        return None
    data = 100 * (data / data.iloc[0])

    ann = ss.ann_factor_for(data.index)
    outs = ss.compute_outrights(data, ann, allow_short=True)
    pairs = ss.compute_pairs(data, ann, MODE)
    pairs, n_capped = ss.apply_ratio_cap(pairs, RATIO_CAP, MODE)
    field = outs + pairs
    if not field:
        return None
    ss.rank_field(field)
    # ER descending, everywhere. ER is scale-free and descriptive, so it stays
    # meaningful on the short windows where Sharpe — an estimate of a forward
    # parameter — does not.
    field.sort(key=lambda c: -(c["ER"] if np.isfinite(c["ER"]) else -9))

    n_bars = len(data)
    span = max((data.index[-1] - data.index[0]).days, 1)
    best_out = next((c for c in field if c["kind"] == "outright"), None)
    best_pair = next((c for c in field if c["kind"] == "pair"), None)
    lg, sh = ss.leg_frequency(field, 20)

    # Every instrument's outright ER, so a pair can be scored against the
    # simpler thing you could have done instead.
    out_er = {ss.name_of(c["sym"]): _num(c["ER"], 3) for c in outs}
    # Which way round each outright is. compute_outrights orients on Sharpe, so
    # a "long GC" in one window can be a "short GC" in another, and an ER matrix
    # that hides that is telling you the size of a move without its sign.
    out_dir = {ss.name_of(c["sym"]): c["dir"] for c in outs}
    # Signed ER, long convention: (last - first) / sum|bar-to-bar|, straight off
    # the price series with no Sharpe orientation in front of it. efficiency()
    # already returns a signed value and already skips unobserved session gaps,
    # so this is the same measure the rest of the tab uses, just not flipped.
    #
    # The oriented figure above stays, because the field ranks on it; this one
    # is for the matrix, where the sign IS the information.
    out_signed = {ss.name_of(sym): _num(ss.efficiency(
        data[sym].pct_change().dropna()), 3) for sym in data.columns}

    def adj(er):
        """ER * sqrt(bars). Raw ER decays as 1/sqrt(n) — a coarser bar traces a
        shorter path over the same net move — so ranking raw ER ACROSS windows
        always flatters the shortest one. Within a window it changes nothing."""
        return None if er is None else _num(er * (n_bars ** 0.5), 2)

    def leg_delta(c):
        """Pair ER against the better of its two legs, as a percentage.

        Negative means the spread did worse than simply holding the better leg,
        which is the number that decides whether the complexity paid.
        """
        if c["kind"] != "pair":
            return None, None
        legs = [out_er.get(ss.name_of(s)) for s in (c["long"], c["short"])]
        legs = [v for v in legs if v is not None]
        if not legs:
            return None, None
        best = max(legs)
        er = _num(c["ER"], 3)
        if er is None or best == 0:
            return _num(best, 3), None
        return _num(best, 3), _num((er - best) / abs(best) * 100, 0)

    rows = []
    for i, c in enumerate(field[:TOP_N], 1):
        best_leg, delta = leg_delta(c)
        er = _num(c["ER"], 3)
        rows.append({
            "n": i, "kind": c["kind"],
            "long": ss.name_of(c["long"]) if c["long"] else None,
            "short": ss.name_of(c["short"]) if c["short"] else None,
            "sector": str(c["Sector"]),
            "sharpe": _num(c["Sharpe"]),
            # Kept in the JSON for site/js/spreads.js, which still reads it.
            # Removed from the Streamlit UI, not from the data contract.
            "score": _num(c["_score"], 1),
            "er": er, "erAdj": adj(er), "win": _num(c["Win%"], 0),
            "tot": _num(c["Tot%"], 1), "vol": _num(c["Vol%"], 1),
            "mdd": _num(c["MDD%"], 1), "corr": _num(c["Corr"]),
            "ratio": _num(c["Ratio"]),
            "bestLegEr": best_leg, "legDelta": delta,
        })

    # Charts follow the table's order, capped so one instrument cannot occupy
    # the grid. Twelve charts of the same short leg is one macro bet drawn
    # twelve times, which leg_frequency already says in a single line.
    charts, seen = [], {}
    for c in field:
        if len(charts) >= CHART_N:
            break
        legs = [s for s in (c["long"], c["short"]) if s]
        if any(seen.get(s, 0) >= MAX_LEG_CHARTS for s in legs):
            continue
        try:
            cv = _curves(c, data, MODE)
        except Exception:
            continue
        for s in legs:
            seen[s] = seen.get(s, 0) + 1
        best_leg, delta = leg_delta(c)
        er = _num(c["ER"], 3)
        cv.update({"n": len(charts) + 1, "label": ss.pos_label(c),
                   "kind": c["kind"], "sharpe": _num(c["Sharpe"]),
                   "er": er, "erAdj": adj(er), "tot": _num(c["Tot%"], 1),
                   # The card carries the same risk columns as the table, so a
                   # shape you like can be sanity-checked without scrolling
                   # back up to find its row.
                   "win": _num(c["Win%"], 0), "vol": _num(c["Vol%"], 1),
                   "mdd": _num(c["MDD%"], 1),
                   "bestLegEr": best_leg, "legDelta": delta})
        charts.append(cv)

    return {
        "window": name, "bar": spec["bar"], "note": spec["note"],
        "bars": n_bars, "instruments": len(data.columns),
        "thin": n_bars < MIN_DISPLAY_BARS,
        "outER": out_er, "outDir": out_dir, "outSigned": out_signed,
        "span": span, "ann": round(ann),
        "se": _num(ss.sharpe_se(span)), "noise": _num(ss.sharpe_se(span) * 2.8, 1),
        "start": data.index[0].strftime("%d %b %H:%M"),
        "end": data.index[-1].strftime("%d %b %H:%M"),
        "nOut": len(outs), "nPair": len(pairs), "nCapped": n_capped,
        "nField": len(field),
        "dropped": [ss.name_of(d) for d in dropped],
        "medOut": _num(np.median([c["Sharpe"] for c in outs])) if outs else 0,
        "medPair": _num(np.median([c["Sharpe"] for c in pairs])) if pairs else 0,
        "bestOut": ss.pos_label(best_out) if best_out else None,
        "outRank": (field.index(best_out) + 1) if best_out else None,
        "bestPair": ss.pos_label(best_pair) if best_pair else None,
        "legShort": [[ss.name_of(k), v] for k, v in sh.most_common(6)],
        "legLong": [[ss.name_of(k), v] for k, v in lg.most_common(6)],
        "rows": rows, "charts": charts,
    }


def _top10_windows(out: dict, top=10) -> dict:
    """{(long, short): [windows where it ranks top-10]}, across ALL nine.

    This replaces the standalone persistence table. The information was right —
    a position holding across neighbouring windows is a different object from
    one that wins the shortest — but as its own section it made you hold two
    tables in your head and cross-reference them by name. As a column it sits on
    the row it describes.

    Spans all nine windows, including the four not in the selector: agreement
    across five calendar windows that share endpoints says much less than
    agreement that also survives the rolling ones.
    """
    seen = {}
    for name, r in out.items():
        for row in r["rows"][:top]:
            key = (row["long"], row["short"])
            seen.setdefault(key, []).append(name)
    return seen


def _persistence(out: dict, top=10):
    """Which candidates hold across windows, not just win one.

    The single most misleading thing a ranked field can do is present the top
    of a 12-day window as a finding. Nine windows disagreeing is the honest
    picture; nine windows agreeing is a signal, and it is the only evidence
    available here that a relationship is structural rather than a fortnight
    of luck. Ranked by count first, then by average rank, because appearing
    8th in six windows beats appearing 1st in one.
    """
    seen = {}
    for name, r in out.items():
        for row in r["rows"][:top]:
            key = ((row["long"] or "cash") + " / " + (row["short"] or "cash"),
                   row["kind"])
            e = seen.setdefault(key, {"windows": [], "ranks": [],
                                      "sharpe": [], "er": []})
            e["windows"].append(name)
            e["ranks"].append(row["n"])
            if row["sharpe"] is not None:
                e["sharpe"].append(row["sharpe"])
            if row["er"] is not None:
                e["er"].append(row["er"])
    rows = []
    for (label, kind), e in seen.items():
        rows.append({
            "label": label, "kind": kind,
            "count": len(e["windows"]), "windows": e["windows"],
            "best": min(e["ranks"]),
            "avgRank": _num(float(np.mean(e["ranks"])), 1),
            "medSharpe": _num(float(np.median(e["sharpe"]))) if e["sharpe"] else None,
            "medER": _num(float(np.median(e["er"])), 3) if e["er"] else None,
        })
    rows.sort(key=lambda r: (-r["count"], r["avgRank"]))
    return rows[:12]


def build_spreads(by_bar: dict) -> dict:
    """by_bar is {bar: {ticker: close Series}} — every window slices from it."""
    out, summary = {}, []
    for name in PERIODS:
        try:
            r = _window_field(name, by_bar)
        except Exception as e:
            print(f"    spreads {name} failed: {str(e)[:70]}")
            r = None
        if r is None:
            print(f"    spreads {name}: not enough data")
            continue
        out[name] = r
        top = r["rows"][0] if r["rows"] else None
        summary.append({
            "window": name, "bars": r["bars"], "se": r["se"],
            "thin": r["thin"],
            "label": (ss.pos_label({"long": top["long"], "short": top["short"]})
                      if top else None),
            "kind": top["kind"] if top else None,
            "er": top["er"] if top else None,
            "erAdj": top["erAdj"] if top else None,
            "tot": top["tot"] if top else None,
            # Static-site keys, unused by the Streamlit render.
            "sharpe": top["sharpe"] if top else None,
            "outRank": r["outRank"], "bestOut": r["bestOut"],
        })
        print(f"    spreads {name}: {r['bars']} bars, {r['instruments']} "
              f"instruments, SE +/-{r['se']}")

    # Attach "also top-10 in" to every row, then drop the window it is already
    # sitting in — a row does not need telling it is in its own table.
    tw = _top10_windows(out)
    for name, r in out.items():
        for row in r["rows"]:
            row["alsoTop"] = [w for w in tw.get((row["long"], row["short"]), [])
                              if w != name]

    return {"periods": [p for p in DISPLAY_PERIODS if p in out],
            # The canonical five, present or not. The by-window table renders a
            # fixed set of rows so the layout does not reflow when a window
            # fails to build or falls under the bar floor.
            "displayPeriods": list(DISPLAY_PERIODS),
            "allPeriods": [p for p in PERIODS if p in out],
            "mode": MODE, "cap": RATIO_CAP, "topN": TOP_N, "summary": summary,
            "minBars": MIN_DISPLAY_BARS, "nWindows": len(out), "data": out,
            # Static-site key. The Streamlit tab carries this as the "also top
            # 10 in" column instead of a section of its own.
            "persist": _persistence(out)}
