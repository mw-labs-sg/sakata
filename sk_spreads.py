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
CHART_N = 6             # candidates that ship a chart series
CHART_PTS = 160         # points per line after decimation

# Point sakata_stats at the live universe so anything added later flows through
# without editing two files.
ss.ALL_SYMBOLS = list(U.TICKERS)
ss.SYMBOL_NAMES = {U.TICKER[c]: c for c in U.CODES}
ss.SYMBOL_SECTOR = {U.TICKER[c]: U.SECTOR[c] for c in U.CODES}

# Bar size per window is chosen so each lands in roughly 60-400 bars. Too few
# and every statistic is noise; too many and an hourly series over a year is a
# daily series with six times the payload and none of the extra information.
WINDOWS = OrderedDict([
    ("Intraday", dict(bar="15m", kind="days",  n=3,   note="15-minute bars, last 3 sessions")),
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
    field.sort(key=lambda c: c["_score"])

    span = max((data.index[-1] - data.index[0]).days, 1)
    best_out = next((c for c in field if c["kind"] == "outright"), None)
    best_pair = next((c for c in field if c["kind"] == "pair"), None)
    lg, sh = ss.leg_frequency(field, 20)

    rows = []
    for i, c in enumerate(field[:TOP_N], 1):
        rows.append({
            "n": i, "kind": c["kind"],
            "long": ss.name_of(c["long"]) if c["long"] else None,
            "short": ss.name_of(c["short"]) if c["short"] else None,
            "sector": str(c["Sector"]),
            "score": _num(c["_score"], 1), "sharpe": _num(c["Sharpe"]),
            "er": _num(c["ER"], 3), "win": _num(c["Win%"], 0),
            "tot": _num(c["Tot%"], 1), "vol": _num(c["Vol%"], 1),
            "mdd": _num(c["MDD%"], 1), "corr": _num(c["Corr"]),
            "ratio": _num(c["Ratio"]),
        })

    charts = []
    for i, c in enumerate(field[:CHART_N], 1):
        try:
            cv = _curves(c, data, MODE)
        except Exception:
            continue
        cv.update({"n": i, "label": ss.pos_label(c), "kind": c["kind"],
                   "sharpe": _num(c["Sharpe"]), "er": _num(c["ER"], 3),
                   "tot": _num(c["Tot%"], 1)})
        charts.append(cv)

    return {
        "window": name, "bar": spec["bar"], "note": spec["note"],
        "bars": len(data), "instruments": len(data.columns),
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
            "label": (r["charts"][0]["label"] if r["charts"] else None),
            "kind": top["kind"] if top else None,
            "sharpe": top["sharpe"] if top else None,
            "er": top["er"] if top else None,
            "tot": top["tot"] if top else None,
            "outRank": r["outRank"], "bestOut": r["bestOut"],
        })
        print(f"    spreads {name}: {r['bars']} bars, {r['instruments']} "
              f"instruments, SE +/-{r['se']}")
    persist = _persistence(out)
    if persist:
        top = persist[0]
        print(f"    spreads: most persistent {top['label']} in "
              f"{top['count']}/{len(out)} windows (avg rank {top['avgRank']})")
    return {"periods": [p for p in PERIODS if p in out], "mode": MODE,
            "cap": RATIO_CAP, "topN": TOP_N, "summary": summary,
            "persist": persist, "nWindows": len(out), "data": out}
