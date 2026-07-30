"""Sakata — spread and outright statistics. Pure numpy/pandas, no Streamlit.

Split out of spreads.py so the same code can run in two places: the Streamlit
app locally, and a GitHub Action that renders a static report. The Action route
exists because Yahoo serves residential IPs but rate-limits cloud ranges, so a
hosted app comes back empty while a runner fetch works fine — the same problem
the exchanges give us on the Curve and Margins tabs, and the same fix.

Nothing here imports streamlit, and nothing caches. Callers own both.
"""
import datetime as _dt
from datetime import datetime
from itertools import combinations

import numpy as np
import pandas as pd

# --------------------------------------------------------------- universe
SECTORS = {
    "Indices":    {"ES": "ES=F", "NQ": "NQ=F"},
    "Bonds":      {"ZB": "ZB=F", "ZN": "ZN=F"},
    "Currencies": {"6E": "6E=F", "6J": "6J=F"},
    "Crypto":     {"BTC": "BTC-USD", "ETH": "ETH-USD"},
    "Energy":     {"CL": "CL=F", "NG": "NG=F"},
    "Metals":     {"GC": "GC=F", "SI": "SI=F", "HG": "HG=F"},
    "Grains":     {"ZC": "ZC=F", "ZW": "ZW=F", "ZS": "ZS=F"},
    "Softs":      {"SB": "SB=F", "KC": "KC=F"},
}
ALL_SYMBOLS = [t for m in SECTORS.values() for t in m.values()]
SYMBOL_NAMES = {t: n for m in SECTORS.values() for n, t in m.items()}
SYMBOL_SECTOR = {t: s for s, m in SECTORS.items() for t in m.values()}


def name_of(sym):
    return SYMBOL_NAMES.get(sym, str(sym).replace("=F", "").replace("-USD", ""))


def sector_of(sym):
    return SYMBOL_SECTOR.get(sym, "—")


def pos_label(c):
    """Readable name for any candidate. A short outright has long=None, which a
    naive lookup would render as the string 'None'."""
    lg, sh = c.get("long"), c.get("short")
    if lg and sh:
        return f"{name_of(lg)}/{name_of(sh)}"
    if lg:
        return f"long {name_of(lg)}"
    if sh:
        return f"short {name_of(sh)}"
    return "—"


# --------------------------------------------------------------- periods
PERIOD_BARS = {"WTD": "1h", "MTD": "4h", "QTD": "1d", "YTD": "1wk"}
BAR_NAMES = {"1h": "1-hour", "4h": "4-hour", "1d": "daily", "1wk": "weekly"}


def period_start(period, now=None):
    now = (now or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "WTD":
        return now - _dt.timedelta(days=now.weekday())
    if period == "MTD":
        return now.replace(day=1)
    if period == "QTD":
        return now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1)
    if period == "YTD":
        return now.replace(month=1, day=1)
    return None


def period_end(period, now=None):
    now = (now or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "WTD":
        return period_start("WTD", now) + _dt.timedelta(days=7)
    if period == "MTD":
        return (now.replace(day=28) + _dt.timedelta(days=8)).replace(day=1)
    if period == "QTD":
        q0 = ((now.month - 1) // 3) * 3 + 1
        return (now.replace(year=now.year + 1, month=1, day=1) if q0 == 10
                else now.replace(month=q0 + 3, day=1))
    if period == "YTD":
        return now.replace(year=now.year + 1, month=1, day=1)
    return None


def sharpe_se(span_days):
    """Standard error of an annualised Sharpe over a calendar span.

    SE = sqrt(annualisation / bars). Annualisation IS bars/years, so the bar
    count cancels exactly and SE = 1/sqrt(years). Bar size is therefore
    irrelevant to Sharpe confidence: 15-minute bars over a month give 92x the
    observations of daily bars and precisely the same standard error. Finer bars
    buy execution granularity, not statistical power.
    """
    return float(1.0 / np.sqrt(max(span_days, 1) / 365.25))


def ann_factor_for(index):
    """Bars per year, measured off the data rather than assumed."""
    if len(index) < 3:
        return 252.0
    yrs = (index[-1] - index[0]).total_seconds() / (365.25 * 24 * 3600)
    if yrs <= 0:
        return 252.0
    return float(np.clip(len(index) / yrs, 12, 8760))


# --------------------------------------------------------------- metrics
def sharpe(r, ann=252):
    if len(r) < 5 or r.std() == 0:
        return 0.0
    return float((r.mean() / r.std()) * np.sqrt(ann))


def sortino(r, ann=252):
    if len(r) < 5 or r.std() == 0:
        return 0.0
    d = r[r < 0]
    ds = np.sqrt(np.mean(d ** 2)) * np.sqrt(ann) if len(d) else 0
    return float(r.mean() * ann / ds) if ds else 0.0


def drawdowns(r):
    cum = (1 + r).cumprod()
    dd = (cum - cum.cummax()) / cum.cummax()
    mdd = float(dd.min() * 100)
    add = float(dd[dd < 0].mean() * 100) if (dd < 0).any() else 0.0
    return mdd, add


def r2_signed(r):
    """Signed R² of the equity curve against a straight line."""
    if len(r) < 5:
        return 0.0
    cum = (1 + r).cumprod().values
    x = np.arange(len(cum))
    n = len(cum)
    xm, ym = x.mean(), cum.mean()
    sxy = np.sum(x * cum) - n * xm * ym
    sxx = np.sum(x * x) - n * xm * xm
    syy = np.sum(cum * cum) - n * ym * ym
    slope = sxy / sxx if sxx else 0
    v = (sxy ** 2) / (sxx * syy) if (sxx * syy) else 0
    v = float(np.clip(v, 0, 1))
    return v if slope > 0 else -v


def efficiency(r):
    """Kaufman efficiency ratio: |net move| / path length, signed.

    1.0 is a straight line, 0.0 is chop that goes nowhere, negative is a clean
    downtrend. Scale-free and purely descriptive, so it stays meaningful on
    short spans where Sharpe — an estimate of a forward parameter — does not.

    Note it IS bar-size dependent: a coarser bar traces a shorter path over the
    same net move, so the same series reads 0.04 hourly and 0.41 weekly. Never
    compare raw ER across different bar sizes; rank within each first.
    """
    if len(r) < 5:
        return 0.0
    cum = (1 + r).cumprod().values
    path = np.abs(np.diff(cum)).sum()
    if path == 0:
        return 0.0
    net = cum[-1] - cum[0]
    er = abs(net) / path
    return float(er if net >= 0 else -er)


def series_stats(r, ann=252):
    """Every metric for one return stream. Shared by outrights and pairs so the
    two are measured identically and can be ranked in a single field."""
    mdd, add = drawdowns(r)
    a = float(r.mean() * ann * 100)
    # MAR divides by average drawdown. On a tight spread over a short window
    # that denominator approaches zero and MAR explodes into the hundreds, so
    # floor it at 50bp and cap the result. Kept for display only — it is not in
    # the composite, because on a 57-bar field it pinned to the cap on 123 of
    # 165 rows and contributed nothing but arbitrary tie-breaking.
    return {
        "Sharpe": sharpe(r, ann), "Sortino": sortino(r, ann),
        "MAR": float(np.clip(a / max(abs(add), 0.5), -99, 99)),
        "R²": r2_signed(r), "ER": efficiency(r),
        "Tot%": float(((1 + r).cumprod().iloc[-1] - 1) * 100),
        "Ann%": a, "Vol%": float(r.std() * np.sqrt(ann) * 100),
        "MDD%": mdd, "ADD%": add,
        "Win%": float((r > 0).sum() / len(r) * 100) if len(r) else 50.0,
    }


# --------------------------------------------------------------- weighting
WEIGHTINGS = {"Equal notional": "equal", "Vol-adjusted": "vol", "Beta-hedged": "beta"}


def weighted_spread(r1, r2, mode):
    """Combine two return streams. Returns (spread_returns, ratio).

    Equal notional lets the high-vol leg dominate — a GC/SI spread sized 1:1
    correlates about -0.97 with silver alone, making it a short silver position
    wearing a spread's clothing. Vol-adjusting gives each leg equal RISK, so the
    ranking reflects the relationship rather than whichever leg is twitchier.
    """
    j = pd.concat([r1, r2], axis=1).dropna()
    a, b = j.iloc[:, 0], j.iloc[:, 1]
    if len(a) < 5:
        return a - b, 1.0
    if mode == "vol":
        s1, s2 = a.std(), b.std()
        if s1 == 0 or s2 == 0:
            return a - b, 1.0
        return (a / s1 - b / s2) * ((s1 + s2) / 2), float(s1 / s2)
    if mode == "beta":
        v2 = b.var()
        beta = float(a.cov(b) / v2) if v2 else 1.0
        return a - beta * b, beta
    return a - b, 1.0


# --------------------------------------------------------------- alignment
MIN_BARS, MIN_SYMBOLS = 20, 8


def align_frames(frames, intraday, min_bars=MIN_BARS, min_symbols=MIN_SYMBOLS):
    """Align {symbol: close Series} by shedding COLUMNS, not rows.

    Dropping rows — an inner join, or ffill then dropna — lets one sparsely
    listed contract govern the whole matrix: ffill cannot backfill a late
    listing, so dropna deletes every row before it, and on intraday the
    intersection collapses to whichever market trades the fewest hours. Both
    were measured cutting a 31-week window to 6 rows and a 73-hour window to 9.
    """
    syms = [k for k, v in frames.items() if v is not None and len(v) > 0]
    if len(syms) < 2:
        return None, [], {}
    union = frames[syms[0]].index
    for s in syms[1:]:
        union = union.union(frames[s].index)
    cov = {k: float(frames[k].reindex(union).notna().mean()) for k in syms}
    order = sorted(syms, key=lambda k: cov[k])
    keep, dropped = list(syms), []
    while True:
        df = pd.DataFrame({k: frames[k] for k in keep})
        df = df.dropna() if intraday else df.ffill().dropna()
        if len(df) >= min_bars or len(keep) <= min_symbols:
            break
        victim = next((k for k in order if k in keep), None)
        if victim is None:
            break
        keep.remove(victim)
        dropped.append(victim)
    if len(df) < 10 or len(df.columns) < 2:
        return None, dropped, cov
    return df, dropped, cov


# --------------------------------------------------------------- candidates
COMPOSITE_WEIGHTS = {"Sharpe": 1.0, "ER": 1.0, "Win%": 1.0}
METRICS = list(COMPOSITE_WEIGHTS)


def compute_outrights(data, ann=252, allow_short=True):
    """Every instrument as a standalone position, oriented on Sharpe exactly as
    pairs are.

    Without the orientation the comparison is rigged: a pair picks its own sign
    and so can never post a negative Sharpe, while a long-only outright eats the
    full loss in any risk-off window. Every outright then sinks for a reason
    that has nothing to do with spreading being better. If you can short a
    pair's leg, you can short it outright.
    """
    out = []
    for sym in data.columns:
        ret = data[sym].pct_change().dropna()
        if len(ret) < 5:
            continue
        is_short = allow_short and sharpe(ret, ann) < 0
        r = -ret if is_short else ret
        row = series_stats(r, ann)
        row.update({"long": None if is_short else sym,
                    "short": sym if is_short else None,
                    "sym": sym, "kind": "outright",
                    "dir": "short" if is_short else "long",
                    "Sector": sector_of(sym), "same_sector": True,
                    "Ratio": float("nan"), "Corr": float("nan")})
        out.append(row)
    return out


def compute_pairs(data, ann=252, mode="equal"):
    """Every long/short combination, sign-oriented so Sharpe reads positive."""
    pairs = []
    rets = {s: data[s].pct_change().dropna() for s in data.columns}
    for s1, s2 in combinations(data.columns.tolist(), 2):
        sp, ratio = weighted_spread(rets[s1], rets[s2], mode)
        if len(sp) < 5:
            continue
        # Orient, then REBUILD. Beta-hedging is not symmetric so a flip is not a
        # negation; and negating Sortino/ER/R² is wrong even when it is, because
        # reversing a series turns the old upside into the new downside.
        if sharpe(sp, ann) < 0:
            s1, s2 = s2, s1
            sp, ratio = weighted_spread(rets[s1], rets[s2], mode)
        row = series_stats(sp, ann)
        sec1, sec2 = sector_of(s1), sector_of(s2)
        same = sec1 == sec2
        row.update({"long": s1, "short": s2, "kind": "pair",
                    "Sector": sec1 if same else f"{sec1[:3]}×{sec2[:3]}",
                    "same_sector": same, "Ratio": ratio,
                    "Corr": float(rets[s1].corr(rets[s2]))})
        pairs.append(row)
    return pairs


def rank_field(cands):
    """Rank outrights and pairs together, then average the ranks.

    One pool is the point: an outright landing at composite rank 3 is a direct
    statement that spreading added nothing over that window.
    """
    n = len(cands)
    if not n:
        return
    for m in METRICS:
        vals = [c[m] for c in cands]
        for rank, i in enumerate(sorted(range(n), key=lambda j: -vals[j])):
            cands[i][f"_{m}_rank"] = rank + 1
    tw = sum(COMPOSITE_WEIGHTS.values())
    for c in cands:
        c["_score"] = float(sum(c[f"_{m}_rank"] * COMPOSITE_WEIGHTS[m]
                                for m in METRICS) / tw)


def apply_ratio_cap(pairs, cap, mode):
    """Drop sizings that cannot be executed. A sigma ratio of 46 means 46 yen
    contracts per coffee contract — a leveraged yen short, not a spread."""
    if not cap or mode == "equal":
        return pairs, 0
    keep = [p for p in pairs if not pd.isna(p["Ratio"])
            and (1 / cap) <= abs(p["Ratio"]) <= cap]
    return keep, len(pairs) - len(keep)


def leg_frequency(cands, top_n=20):
    """How often each ticker appears in the top N.

    A field of 153 pairs is not 153 independent candidates. When one instrument
    is the short leg of twelve of the top twenty, the table is one macro bet
    replicated against whatever rallied — and the honest expression of it is the
    outright, not the twelve spreads.
    """
    from collections import Counter
    lg, sh = Counter(), Counter()
    for c in cands[:top_n]:
        if c.get("long"):
            lg[c["long"]] += 1
        if c.get("short"):
            sh[c["short"]] += 1
    return lg, sh
