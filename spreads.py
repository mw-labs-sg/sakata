import streamlit as st
import yfinance as yf

from common import _session
import pandas as pd
import numpy as np
import datetime as _dt
from datetime import datetime
from itertools import combinations
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging

from sakata_config import (ALL_SYMBOLS, THEMES, SYMBOL_NAMES, FONTS, clean_symbol,
                           FUTURES_GROUPS, SYMBOL_SECTOR)

logger = logging.getLogger(__name__)

# =============================================================================
# STATISTICS
# =============================================================================

def _sharpe(returns, ann_factor=252):
    if len(returns) < 5 or returns.std() == 0:
        return 0.0
    return float((returns.mean() / returns.std()) * np.sqrt(ann_factor))


def _sortino(returns, ann_factor=252):
    if len(returns) < 5 or returns.std() == 0:
        return 0.0
    ann_ret = returns.mean() * ann_factor
    down = returns[returns < 0]
    down_std = np.sqrt(np.mean(down ** 2)) * np.sqrt(ann_factor) if len(down) > 0 else 0
    return float(ann_ret / down_std) if down_std else 0.0


def _drawdowns(returns):
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = float(dd.min() * 100)
    add = float(dd[dd < 0].mean() * 100) if (dd < 0).any() else 0.0
    return mdd, add


def _r2(returns):
    """Signed R² of the equity curve against a straight line."""
    if len(returns) < 5:
        return 0.0
    cum = (1 + returns).cumprod().values
    x = np.arange(len(cum))
    xm, ym = x.mean(), cum.mean()
    ss_xy = np.sum(x * cum) - len(cum) * xm * ym
    ss_xx = np.sum(x * x) - len(cum) * xm * xm
    ss_yy = np.sum(cum * cum) - len(cum) * ym * ym
    slope = ss_xy / ss_xx if ss_xx else 0
    r2 = (ss_xy ** 2) / (ss_xx * ss_yy) if (ss_xx * ss_yy) else 0
    r2 = float(np.clip(r2, 0, 1))
    return r2 if slope > 0 else -r2


def _efficiency(returns):
    """Kaufman efficiency ratio on the equity curve: |net move| / path length.

    1.0 = a perfectly straight line, 0.0 = pure chop that goes nowhere. Signed,
    so a smooth DOWNtrend scores -1.0 rather than +1.0. Unlike R² it is
    scale-free and assumes no linearity — it only asks how much of the distance
    travelled was actually retained.
    """
    if len(returns) < 5:
        return 0.0
    cum = (1 + returns).cumprod().values
    path = np.abs(np.diff(cum)).sum()
    if path == 0:
        return 0.0
    net = cum[-1] - cum[0]
    er = abs(net) / path
    return float(er if net >= 0 else -er)


def series_stats(returns, ann_factor=252):
    """Every metric for one return stream. Shared by outrights AND pairs so the
    two are measured identically and can be ranked in a single field."""
    mdd, add = _drawdowns(returns)
    ann = float(returns.mean() * ann_factor * 100)
    # MAR divides by average drawdown. On a tight low-vol spread over a short
    # window that denominator approaches zero and MAR explodes into the
    # hundreds, which then dominates the composite. Floor it at 50bp — below
    # that a drawdown is not distinguishable from noise — and cap the result.
    mar = float(np.clip(ann / max(abs(add), 0.5), -99, 99))
    return {
        'Sharpe': _sharpe(returns, ann_factor),
        'Sortino': _sortino(returns, ann_factor),
        'MAR': mar,
        'R²': _r2(returns),
        'ER': _efficiency(returns),
        'Tot%': float(((1 + returns).cumprod().iloc[-1] - 1) * 100),
        'Ann%': ann,
        'Vol%': float(returns.std() * np.sqrt(ann_factor) * 100),
        'MDD%': mdd, 'ADD%': add,
        'Win%': float((returns > 0).sum() / len(returns) * 100) if len(returns) else 50.0,
    }


# =============================================================================
# LEG WEIGHTING
# =============================================================================

WEIGHTINGS = {
    'Equal notional': 'equal',
    'Vol-adjusted': 'vol',
    'Beta-hedged': 'beta',
}
WEIGHT_BLURB = {
    'equal': ("r₁ − r₂, one unit each. Simple, but the high-vol leg dominates — "
              "a GC/SI spread sized this way correlates about −0.97 with silver "
              "alone, so it is a short silver position wearing a spread's clothing."),
    'vol': ("r₁/σ₁ − r₂/σ₂, rescaled to the average leg vol. Each leg contributes "
            "equal RISK rather than equal notional, so the ranking reflects the "
            "relationship instead of whichever leg happens to be more volatile. "
            "σ RATIO is σ₁/σ₂ — units of the short leg per unit of the long."),
    'beta': ("r₁ − β·r₂, with β from the in-window regression. Strips the short "
             "leg's directional influence entirely — residual correlation to leg 2 "
             "is zero by construction — isolating leg 1's idiosyncratic move. "
             "Unstable when the legs are only weakly related."),
}


# Above this the vol-adjusted sizing stops being executable: a sigma ratio of
# 46 means 46 yen contracts per coffee contract, which is a leveraged yen short
# with a coffee garnish, not a spread.
RATIO_WARN = 5.0
RATIO_CAPS = {'Off': None, '3:1': 3.0, '5:1': 5.0, '10:1': 10.0}


def _weighted_spread(r1, r2, mode):
    """Combine two aligned return streams. Returns (spread_returns, ratio)."""
    j = pd.concat([r1, r2], axis=1).dropna()
    a, b = j.iloc[:, 0], j.iloc[:, 1]
    if len(a) < 5:
        return a - b, 1.0
    if mode == 'vol':
        s1, s2 = a.std(), b.std()
        if s1 == 0 or s2 == 0:
            return a - b, 1.0
        tgt = (s1 + s2) / 2          # keep magnitudes readable as returns
        return (a / s1 - b / s2) * tgt, float(s1 / s2)
    if mode == 'beta':
        v2 = b.var()
        beta = float(a.cov(b) / v2) if v2 else 1.0
        return a - beta * b, beta
    return a - b, 1.0


# =============================================================================
# LOOKBACK PERIODS AND BARS
# =============================================================================

# Calendar-anchored periods -> the bar size each defaults to. These are anchors,
# not rolling windows: QTD on 1 July is one day long, not ninety.
PERIOD_BARS = {'DTD': '15m', 'WTD': '1h', 'MTD': '4h', 'QTD': '1d', 'YTD': '1wk'}

ROLLING_DAYS = {
    '1 Day': 1, '5 Days': 5, '10 Days': 10, '20 Days': 20, '30 Days': 30,
    '60 Days': 60, '120 Days': 120, '240 Days': 240, '520 Days': 520,
}
LOOKBACK_OPTIONS = list(PERIOD_BARS) + list(ROLLING_DAYS)

# Yahoo intraday limits: 15m/30m reach back ~60 days, 1h ~730 days. There is no
# native 4h bar — it is resampled from 1h.
BAR_OPTIONS = {'Auto': None, '15 Min': '15m', '30 Min': '30m', '1 Hour': '1h',
               '4 Hour': '4h', 'Daily': '1d', 'Weekly': '1wk'}
_INTRADAY = ('15m', '30m', '1h', '4h')
_NATIVE = {'15m': '15m', '30m': '30m', '1h': '1h', '4h': '1h',
           '1d': '1d', '1wk': '1wk'}
_MAX_BACK = {'15m': 55, '30m': 55, '1h': 700, '4h': 700, '1d': None, '1wk': None}
BAR_NAMES = {'15m': '15-minute', '30m': '30-minute', '1h': '1-hour',
             '4h': '4-hour', '1d': 'daily', '1wk': 'weekly'}
BAR_SHORT = {'15m': '15m', '30m': '30m', '1h': '1H', '4h': '4H',
             '1d': '1D', '1wk': '1W'}

_LADDER = ((2, '15m'), (7, '30m'), (20, '1h'), (60, '4h'))

MIN_BARS = 20        # below this a window is not worth ranking a field on
MIN_SYMBOLS = 8      # never thin the universe past this to chase bar count
_FINER = {'1wk': '1d', '1d': '4h', '4h': '1h', '1h': '30m', '30m': '15m', '15m': None}


def auto_interval(lookback_days):
    """Short windows get finer bars — 30 daily closes is not a sample."""
    if lookback_days == 0:
        return '1d'
    for limit, interval in _LADDER:
        if lookback_days <= limit:
            return interval
    return '1d'


def period_start(period, now=None):
    """Calendar anchor for WTD / MTD / QTD / YTD, at midnight."""
    now = (now or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'DTD':
        return now
    if period == 'WTD':
        return now - _dt.timedelta(days=now.weekday())      # Monday
    if period == 'MTD':
        return now.replace(day=1)
    if period == 'QTD':
        return now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1)
    if period == 'YTD':
        return now.replace(month=1, day=1)
    return None


def period_end(period, now=None):
    """Close of the current calendar period — the natural exit for the trade."""
    now = (now or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'DTD':
        return now + _dt.timedelta(days=1)
    if period == 'WTD':
        return period_start('WTD', now) + _dt.timedelta(days=7)
    if period == 'MTD':
        return (now.replace(day=28) + _dt.timedelta(days=8)).replace(day=1)
    if period == 'QTD':
        q0 = ((now.month - 1) // 3) * 3 + 1
        return (now.replace(year=now.year + 1, month=1, day=1) if q0 == 10
                else now.replace(month=q0 + 3, day=1))
    if period == 'YTD':
        return now.replace(year=now.year + 1, month=1, day=1)
    return None


def sharpe_se(span_days):
    """Standard error of an annualised Sharpe over a given calendar span.

    SE = sqrt(annualisation / bars). Since annualisation IS bars/years, the bar
    count cancels exactly and SE = 1/sqrt(years). Bar size is therefore
    irrelevant to Sharpe confidence: 15-minute bars over a month give 92x the
    observations of daily bars and precisely the same standard error. Finer bars
    buy execution granularity, not statistical power.
    """
    return float(1.0 / np.sqrt(max(span_days, 1) / 365.25))


# Metrics that estimate a forward-looking parameter, and so need a real sample.
INFERENTIAL_FITNESS = ('Composite', 'Sharpe', 'Sortino', 'MAR')
# Metrics that describe what demonstrably happened in the window. Readable in
# 30 bars because they make no claim about the future.
DESCRIPTIVE_FITNESS = ('ER (efficiency)', 'Total', 'Win Rate', 'R² (linearity)')


def fitness_advice(span_days, chosen):
    """Whether the chosen fitness function is supportable over this span."""
    se = sharpe_se(span_days)
    if chosen in INFERENTIAL_FITNESS and se > 2.5:
        return ('bad', se,
                f"**{chosen}** is a t-statistic in disguise, and over {span_days} "
                f"calendar days its standard error is ±{se:.1f}. A Sharpe of 6 is "
                f"barely two SE from zero. Rank by **ER (efficiency)** or "
                f"**Total** instead — those describe what the window actually did "
                f"rather than estimating a forward parameter, so they stay "
                f"readable on a short span. Changing the bar size will not help: "
                f"SE depends only on calendar span.")
    if chosen in INFERENTIAL_FITNESS and se > 1.5:
        return ('warn', se,
                f"**{chosen}** carries a standard error of ±{se:.1f} over "
                f"{span_days} days — usable for sorting, too loose for sizing. "
                f"Cross-check against **ER**.")
    return ('ok', se,
            f"**{chosen}** is supportable over {span_days} days "
            f"(Sharpe SE ±{se:.1f}).")


def period_progress(period, data):
    """How full the period's sample is, and how full it will get by the close."""
    s0, e0 = period_start(period), period_end(period)
    if s0 is None or e0 is None:
        return None
    total = max((e0 - s0).days, 1)
    elapsed = min(max((datetime.now() - s0).days, 1), total)
    return {'total_days': total, 'elapsed_days': elapsed,
            'frac': elapsed / total, 'bars_now': len(data),
            'bars_proj': int(len(data) / elapsed * total),
            'se_now': sharpe_se(elapsed), 'se_end': sharpe_se(total),
            'ends': e0}


def thesis_drift(data, cands, mode, top_n=12):
    """Split the window in half and re-measure each top candidate, holding its
    orientation fixed.

    This is the stop rule. A spread whose first half was strong and second half
    negative has already broken, whatever the calendar says — the period
    boundary is a planned exit, but a thesis break is an unplanned one and it
    comes first. Correlation drift shows WHY: when two legs stop moving
    together, the relationship the spread was built on no longer exists.
    """
    k = len(data) // 2
    if k < 8 or len(data) - k < 8:
        return []
    a, b = data.iloc[:k], data.iloc[k:]
    ann_a, ann_b = ann_factor_for(a.index), ann_factor_for(b.index)
    out = []
    for c in cands[:top_n]:
        lg, sh = c.get('long'), c.get('short')
        try:
            if lg and sh:
                ra = _weighted_spread(a[lg].pct_change().dropna(),
                                      a[sh].pct_change().dropna(), mode)[0]
                rb = _weighted_spread(b[lg].pct_change().dropna(),
                                      b[sh].pct_change().dropna(), mode)[0]
                c1 = float(a[lg].pct_change().corr(a[sh].pct_change()))
                c2 = float(b[lg].pct_change().corr(b[sh].pct_change()))
            elif lg:
                ra, rb = a[lg].pct_change().dropna(), b[lg].pct_change().dropna()
                c1 = c2 = float('nan')
            else:
                ra, rb = -a[sh].pct_change().dropna(), -b[sh].pct_change().dropna()
                c1 = c2 = float('nan')
            if len(ra) < 5 or len(rb) < 5:
                continue
            s1, s2 = _sharpe(ra, ann_a), _sharpe(rb, ann_b)
            out.append({
                'label': f"{'cash' if lg is None else SYMBOL_NAMES.get(lg, clean_symbol(lg))}"
                         f"/{'cash' if sh is None else SYMBOL_NAMES.get(sh, clean_symbol(sh))}",
                'kind': c['kind'], 'sh_h1': s1, 'sh_h2': s2, 'delta': s2 - s1,
                'er_h1': _efficiency(ra), 'er_h2': _efficiency(rb),
                'corr_h1': c1, 'corr_h2': c2,
                'broken': s1 > 0 and s2 < 0,
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def ann_factor_for(index):
    """Bars per year, measured off the data rather than assumed.

    Self-calibrating: a year of daily closes gives ~252, a 30-day window of 4h
    bars gives ~1500, weekly gives ~52. Keeps Sharpe/Sortino/vol comparable.
    """
    if len(index) < 3:
        return 252.0
    span_yrs = (index[-1] - index[0]).total_seconds() / (365.25 * 24 * 3600)
    if span_yrs <= 0:
        return 252.0
    return float(np.clip(len(index) / span_yrs, 12, 8760))


# =============================================================================
# DATA FETCHING
# =============================================================================

def _align_frames(frames, intraday, min_bars=MIN_BARS, min_symbols=MIN_SYMBOLS):
    """Align {symbol: close Series} into one matrix by shedding COLUMNS.

    Dropping rows — an inner join, or ffill then dropna — lets a single
    sparsely-listed contract govern the whole matrix: ffill cannot backfill a
    late listing, so dropna deletes every row before it, and on intraday the
    intersection collapses to whichever market trades the fewest hours.

    So rank symbols by how much of the union index they cover and shed the
    worst until the matrix clears min_bars or the universe hits min_symbols.
    """
    syms = [k for k, v in frames.items() if v is not None and len(v) > 0]
    if len(syms) < 2:
        return None, [], {}
    union = frames[syms[0]].index
    for s in syms[1:]:
        union = union.union(frames[s].index)
    cov = {k: float(frames[k].reindex(union).notna().mean()) for k in syms}
    order = sorted(syms, key=lambda k: cov[k])     # worst coverage first

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


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_spread_data(symbols_tuple, lookback_days=0, interval='1d', start_iso=None):
    """Rebased (=100) close matrix, plus a coverage report.

    Daily/weekly bars are forward-filled before alignment. Intraday bars are
    NOT — a stale grain price carried through a closed session would show as a
    zero return and flatter the vol and Sharpe.

    start_iso pins an absolute calendar start (the WTD/MTD/QTD/YTD anchors) and
    takes precedence over lookback_days. Never returns a bare None, so the
    caller can explain WHY a window came back empty.
    """
    blank = {'data': None, 'raw': {}, 'cov': {}, 'dropped': [], 'interval': interval}
    symbols = list(symbols_tuple)
    if len(symbols) < 2:
        return blank
    intraday = interval in _INTRADAY
    yf_interval = _NATIVE[interval]

    if start_iso:
        start = datetime.fromisoformat(start_iso)
    elif lookback_days == 0:
        start = datetime.now().replace(month=1, day=1)
    else:
        pad = 3 if lookback_days <= 5 else 1.5   # short windows need weekend slack
        start = datetime.now() - pd.Timedelta(days=int(lookback_days * pad) + 2)
    cap = _MAX_BACK.get(interval)
    if cap:
        start = max(start, datetime.now() - pd.Timedelta(days=cap))

    # Reach back a little before the anchor so a bar straddling the boundary is
    # not clipped, then trim to the anchor after aligning.
    fetch_start = start - pd.Timedelta(days=10 if interval in ('1wk', '1d') else 2)

    frames, raw = {}, {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym, session=_session).history(
                start=fetch_start.strftime('%Y-%m-%d'), interval=yf_interval)
            if hist.empty:
                raw[sym] = 0
                continue
            closes = hist['Close'].copy()
            closes.index = closes.index.tz_localize(None) if closes.index.tz else closes.index
            if intraday:
                if interval == '4h':
                    closes = closes.resample('4h').last().dropna()
            else:
                closes.index = closes.index.normalize()
            closes = closes.groupby(closes.index).last()
            frames[sym] = closes
            raw[sym] = len(closes)
        except Exception as e:
            raw[sym] = 0
            logger.debug(f"[{sym}] spread data fetch error: {e}")

    data, dropped, cov = _align_frames(frames, intraday)
    report = {'data': None, 'raw': raw, 'cov': cov, 'dropped': dropped,
              'interval': interval}
    if data is None:
        return report

    if start_iso:
        data = data[data.index >= pd.Timestamp(start_iso)]
    elif lookback_days > 0 and not data.empty:
        cutoff = data.index.max() - pd.Timedelta(days=lookback_days)
        data = data[data.index >= cutoff]
    if len(data) < 10 or len(data.columns) < 2:
        return report

    report['data'] = 100 * (data / data.iloc[0])
    return report


# =============================================================================
# CANDIDATES — outrights and pairs, measured the same way
# =============================================================================

METRICS = ['Sharpe', 'Sortino', 'MAR', 'R²', 'ER']


def _sector_of(sym):
    return SYMBOL_SECTOR.get(sym, '—')


def compute_outrights(data, ann_factor=252, allow_short=True):
    """Every instrument as a standalone position — the benchmark field.

    Oriented on Sharpe exactly as pairs are. Without this the comparison is
    rigged: a pair gets to pick its sign and so can never post a negative
    Sharpe, while a long-only outright eats the full loss in any risk-off
    window. Every outright then sinks to the bottom of the field for a reason
    that has nothing to do with spreading being better. If you can short a
    pair's leg you can short it outright, so the sign flip must apply to both.
    """
    out = []
    for sym in data.columns:
        ret = data[sym].pct_change().dropna()
        if len(ret) < 5:
            continue
        is_short = allow_short and _sharpe(ret, ann_factor) < 0
        r = -ret if is_short else ret
        row = series_stats(r, ann_factor)
        eq = 100 * (1 + r).cumprod()
        row.update({'long': None if is_short else sym,
                    'short': sym if is_short else None,
                    'sym': sym, 'kind': 'outright',
                    'dir': 'short' if is_short else 'long',
                    'Sector': _sector_of(sym), 'same_sector': True,
                    'Ratio': float('nan'), 'Corr': float('nan'),
                    'cum_long': eq, 'cum_short': None, 'cum_spread': eq})
        out.append(row)
    return out


def compute_pairs(data, ann_factor=252, mode='equal'):
    """Every long/short combination, sign-oriented so Sharpe reads positive."""
    pairs = []
    rets = {s: data[s].pct_change().dropna() for s in data.columns}
    for s1, s2 in combinations(data.columns.tolist(), 2):
        spread_ret, ratio = _weighted_spread(rets[s1], rets[s2], mode)
        if len(spread_ret) < 5:
            continue

        # Orient on Sharpe, then REBUILD the spread for the swapped legs.
        # Beta-hedging is not symmetric, so a flip is not a negation; and
        # negating Sortino/ER/R² is wrong even when it is, because reversing a
        # series turns the old upside into the new downside deviation.
        if _sharpe(spread_ret, ann_factor) < 0:
            s1, s2 = s2, s1
            spread_ret, ratio = _weighted_spread(rets[s1], rets[s2], mode)

        row = series_stats(spread_ret, ann_factor)

        cum_sp = pd.Series(100.0, index=data.index[:1])
        cum_sp = pd.concat([cum_sp, 100 * (1 + spread_ret).cumprod()])
        cum_sp = cum_sp[~cum_sp.index.duplicated(keep='last')]

        sec1, sec2 = _sector_of(s1), _sector_of(s2)
        same = sec1 == sec2
        row.update({'long': s1, 'short': s2, 'kind': 'pair',
                    'Sector': sec1 if same else f"{sec1[:3]}×{sec2[:3]}",
                    'same_sector': same, 'Ratio': ratio,
                    'Corr': float(rets[s1].corr(rets[s2])),
                    'cum_long': data[s1], 'cum_short': data[s2],
                    'cum_spread': cum_sp})
        pairs.append(row)
    return pairs


def score_position(data, long_sym, short_sym, mode, ann_factor):
    """Stats for a FIXED orientation — no sign flip.

    Essential for the cross-period snapshot. If each period were allowed to
    orient itself, a pair could show as long GC/short 6J on the quarter and the
    reverse on the week, and the columns would not be comparable. Orientation is
    set once by the primary period and every other column measures that same
    position.
    """
    try:
        if long_sym and short_sym:
            r = _weighted_spread(data[long_sym].pct_change().dropna(),
                                 data[short_sym].pct_change().dropna(), mode)[0]
        elif long_sym:
            r = data[long_sym].pct_change().dropna()
        elif short_sym:
            r = -data[short_sym].pct_change().dropna()
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    if len(r) < 5:
        return None
    return series_stats(r, ann_factor)


# =============================================================================
# CROSS-PERIOD SNAPSHOT
# =============================================================================

def resample_view(df_1h, bar):
    """Derive a coarser view from one 1-hour matrix.

    4h / daily / weekly are all obtainable by resampling 1h, and 1h reaches back
    700 days on Yahoo — far enough to cover YTD. So the whole ladder comes from a
    single fetch instead of four, which matters because the fetch is the slow
    part. The statistics are unaffected: Sharpe SE depends only on calendar span.
    """
    rule = {'1h': None, '4h': '4h', '1d': '1D', '1wk': 'W-MON'}[bar]
    out = df_1h if rule is None else df_1h.resample(rule).last()
    out = out.dropna(how='all').ffill().dropna()
    if len(out) < 5:
        return None
    return 100 * (out / out.iloc[0])


@st.cache_data(ttl=1800, show_spinner=False)
def build_snapshot(symbols_tuple, primary, mode, universe, _stamp=None):
    """One row per candidate, one column per period, orientation fixed.

    Returns (rows, meta). Each row carries the full stat block for the primary
    period plus the chosen metric for every period, so persistence across
    horizons is readable at a glance — a position positive on the quarter, the
    month AND the week is a far stronger claim than any single window.
    """
    ytd0 = period_start('YTD')
    res = fetch_spread_data(symbols_tuple, 0, '1h', ytd0.isoformat())
    if res['data'] is None:
        return None, {'error': 'no 1h data', 'report': res}
    # 15m cannot be derived from 1h, so DTD gets its own small pull. Everything
    # coarser than an hour is resampled off the single 1h matrix.
    res15 = fetch_spread_data(symbols_tuple, 3, '15m', None)

    base = res['data']
    views, meta = {}, {'report': res, 'periods': {}}
    for per, bar in PERIOD_BARS.items():
        src = res15['data'] if bar == '15m' else base
        if src is None:
            continue
        sub = src[src.index >= pd.Timestamp(period_start(per))]
        v = resample_view(sub, bar if bar != '15m' else '1h') if len(sub) else None
        if bar == '15m' and len(sub) >= 5:
            v = 100 * (sub / sub.iloc[0])
        if v is None:
            continue
        views[per] = v
        meta['periods'][per] = {
            'bar': bar, 'bars': len(v),
            'span': max((datetime.now() - period_start(per)).days, 1),
            'se': sharpe_se(max((datetime.now() - period_start(per)).days, 1)),
            'ann': ann_factor_for(v.index)}
    if primary not in views:
        primary = next(iter(views), None)
    if primary is None:
        return None, {'error': 'no usable period views', 'report': res}
    meta['primary'] = primary

    prim = views[primary]
    ann_p = meta['periods'][primary]['ann']
    outs = compute_outrights(prim, ann_p, allow_short=True)
    pairs = compute_pairs(prim, ann_p, mode)
    outs, pairs = filter_universe(outs, pairs, universe)
    cands = outs + pairs

    for c in cands:
        for per, v in views.items():
            a = meta['periods'][per]['ann']
            stt = score_position(v, c.get('long'), c.get('short'), mode, a)
            for m in ('ER', 'Sharpe', 'Tot%', 'Vol%'):
                c[f'{m}@{per}'] = stt[m] if stt else float('nan')
        vals = [c.get(f'ER@{p}') for p in views]
        good = [v for v in vals if not pd.isna(v)]
        c['align'] = sum(1 for v in good if v > 0)
        c['align_n'] = len(good)
        c['align_txt'] = f"{c['align']}/{c['align_n']}"
    return cands, meta


# =============================================================================
# UNIVERSE FILTERING
# =============================================================================

UNIVERSE_ALL = 'All cross-asset'
UNIVERSE_INTRA = 'Within sector only'


def _legs_of(c):
    """Tickers a candidate touches. A short outright has long=None."""
    return {x for x in (c.get('long'), c.get('short')) if x}


def universe_options():
    return [UNIVERSE_ALL, UNIVERSE_INTRA] + list(FUTURES_GROUPS)


def filter_universe(outs, pairs, universe):
    """Restrict the field BEFORE ranking, so ranks are relative to what you
    asked for. Picking Metals ranks GC/SI/HG against each other, not against
    Bitcoin."""
    if universe == UNIVERSE_ALL:
        return outs, pairs
    if universe == UNIVERSE_INTRA:
        return outs, [p for p in pairs if p['same_sector']]
    syms = set(FUTURES_GROUPS.get(universe, []))
    return ([o for o in outs if _legs_of(o) <= syms],
            [p for p in pairs if _legs_of(p) <= syms])


# =============================================================================
# RANKING — one combined field
# =============================================================================

SORT_KEYS = {
    'Composite': '_score', 'Sharpe': 'Sharpe', 'Sortino': 'Sortino',
    'MAR': 'MAR', 'R² (linearity)': 'R²', 'ER (efficiency)': 'ER',
    'Total': 'Tot%', 'Win Rate': 'Win%',
}
LOWER_IS_BETTER = ('_score',)
TYPE_FILTERS = ['Outrights + pairs', 'Pairs only', 'Outrights only']


def rank_field(candidates):
    """Rank outrights and pairs together on every metric, then average the ranks.
    Because both sit in one pool, an outright landing at composite rank 3 is a
    direct statement that spreading added nothing over that window."""
    n = len(candidates)
    if n == 0:
        return
    for metric in METRICS:
        vals = [c[metric] for c in candidates]
        order = sorted(range(n), key=lambda i: -vals[i])
        for rank, idx in enumerate(order):
            candidates[idx][f'_{metric}_rank'] = rank + 1
    for c in candidates:
        c['_score'] = float(np.mean([c[f'_{m}_rank'] for m in METRICS]))


def apply_field_rank(candidates, sort_key):
    key = SORT_KEYS.get(sort_key, sort_key)
    lower = key in LOWER_IS_BETTER
    order = sorted(range(len(candidates)),
                   key=lambda i: candidates[i].get(key, 0), reverse=not lower)
    for rank, idx in enumerate(order):
        candidates[idx]['_field'] = rank + 1
    return key, lower


def sort_candidates(cands, sort_key='Composite', ascending=False):
    key = SORT_KEYS.get(sort_key, sort_key)
    default_reverse = key not in LOWER_IS_BETTER
    reverse = not default_reverse if ascending else default_reverse
    return sorted(cands, key=lambda x: x.get(key, 0), reverse=reverse)


# =============================================================================
# REDUNDANCY + DIGEST
# =============================================================================

def leg_frequency(cands, top_n=20):
    """How often each ticker appears as a long or a short in the top N.

    A field of 153 pairs is not 153 independent candidates. When one instrument
    is the short leg of twelve of the top twenty, the table is one macro bet
    replicated against whatever rallied — and the honest expression of it is the
    outright, not the twelve spreads.
    """
    from collections import Counter
    lg, sh = Counter(), Counter()
    for c in cands[:top_n]:
        if c.get('long'):
            lg[c['long']] += 1
        if c.get('short'):
            sh[c['short']] += 1
    return lg, sh


def build_digest(field, table_rows, data, ctx, top_n=25):
    """Compact fixed-width digest of the whole run, sized to paste into a chat.

    The full 171-row HTML table is unreadable once pasted — it loses the column
    alignment and buries the summary statistics. This keeps the diagnostics that
    actually determine whether anything here is real: sample size, Sharpe
    standard error, the noise threshold, outright-vs-pair verdict, and leg
    concentration.
    """
    L = []
    A = L.append
    A("SAKATA / SPREADS DIGEST")
    A(f"generated       {datetime.now():%Y-%m-%d %H:%M}")
    A(f"window          {ctx['window']}")
    A(f"bars            {ctx['bar']}  ({len(data)} observations, annualised x{ctx['ann']:,.0f})")
    A(f"instruments     {len(data.columns)}  |  universe: {ctx['universe']}")
    A(f"leg weighting   {ctx['weighting']}   ratio cap: {ctx['ratio_cap']}")
    A(f"fitness         {ctx['fitness']}")
    A(f"field           {ctx['n_out']} outrights + {ctx['n_pair']} pairs = {len(field)} candidates")

    se = (ctx['ann'] / len(data)) ** 0.5
    A("")
    A("-- SIGNIFICANCE ------------------------------------------------")
    A(f"Sharpe standard error   +/-{se:.2f}   ({len(data)} bars)")
    outs = [c for c in field if c['kind'] == 'outright']
    prs = [c for c in field if c['kind'] == 'pair']
    if prs:
        bp = max(prs, key=lambda c: c['Sharpe'])
        A(f"best pair Sharpe        {bp['Sharpe']:.2f}  = {bp['Sharpe']/se:.2f} SE")
        A(f"median pair Sharpe      {np.median([c['Sharpe'] for c in prs]):.2f}")
    if outs:
        bo = max(outs, key=lambda c: c['Sharpe'])
        A(f"best outright Sharpe    {bo['Sharpe']:.2f}  = {bo['Sharpe']/se:.2f} SE")
        A(f"median outright Sharpe  {np.median([c['Sharpe'] for c in outs]):.2f}")
    if outs and prs:
        bo = max(outs, key=lambda c: c['Sharpe'])
        nb = sum(1 for c in prs if c['Sharpe'] > bo['Sharpe'])
        A(f"pairs beating best outright  {nb}/{len(prs)}  ({nb/len(prs):.0%})")
        top10 = sorted(field, key=lambda c: c.get('_field', 9999))[:10]
        A(f"outrights in top ten    {sum(1 for c in top10 if c['kind']=='outright')}/10")

    lg, sh = leg_frequency(table_rows, 20)
    if sh:
        A("")
        A("-- LEG CONCENTRATION IN TOP 20 ---------------------------------")
        A("short legs: " + "  ".join(
            f"{SYMBOL_NAMES.get(k, clean_symbol(k))}x{v}" for k, v in sh.most_common(6)))
        A("long legs:  " + "  ".join(
            f"{SYMBOL_NAMES.get(k, clean_symbol(k))}x{v}" for k, v in lg.most_common(6)))

    A("")
    A(f"-- TOP {top_n} BY {ctx['fitness'].upper()} " + "-" * max(0, 44 - len(ctx['fitness'])))
    A(f"{'#':>3} {'LONG':<6}{'SHORT':<6}{'SECTOR':<9}{'RATIO':>7}"
      f"{'SCORE':>7}{'SHRP':>7}{'SORT':>7}{'MAR':>7}{'R2':>7}{'ER':>7}"
      f"{'WIN%':>6}{'TOT%':>8}{'VOL%':>8}{'MDD%':>7}{'CORR':>7}")
    for i, c in enumerate(table_rows[:top_n], 1):
        ln = 'cash' if c['long'] is None else SYMBOL_NAMES.get(c['long'], clean_symbol(c['long']))
        sn = 'cash' if c['short'] is None else SYMBOL_NAMES.get(c['short'], clean_symbol(c['short']))
        rt = '   -  ' if pd.isna(c['Ratio']) else f"{c['Ratio']:7.2f}"
        cr = '   -  ' if pd.isna(c['Corr']) else f"{c['Corr']:7.2f}"
        A(f"{i:>3} {ln:<6}{sn:<6}{str(c.get('Sector','-'))[:8]:<9}{rt}"
          f"{c.get('_score',0):7.1f}{c['Sharpe']:7.2f}{c['Sortino']:7.2f}"
          f"{c['MAR']:7.1f}{c['R²']:7.3f}{c['ER']:7.3f}{c['Win%']:6.0f}"
          f"{c['Tot%']:+8.2f}{c['Vol%']:8.1f}{c['MDD%']:7.2f}{cr}")
    if ctx.get('dropped'):
        A("")
        A("dropped for thin coverage: " + ", ".join(
            SYMBOL_NAMES.get(x, clean_symbol(x)) for x in ctx['dropped']))
    return "\n".join(L)


def score_cells(rows, periods):
    """Percentile-rank each position WITHIN each horizon, then pick its best cell.

    Raw ER cannot be compared across horizons. Kaufman efficiency is
    |net move| / path length, and a coarser bar traces a shorter path over the
    same move — measured on one identical price series ER reads 0.04 on hourly
    bars and 0.41 on weekly. Rank cells on the raw number and you sort by
    timeframe, not by trade quality.

    Ranking within a column removes that entirely: the question becomes "how
    exceptional is this position among its peers on the same horizon", which IS
    comparable across horizons. The winning cell then answers the real question —
    trade WHAT, on WHICH holding period.
    """
    n_rows = len(rows)
    if not n_rows:
        return
    for per in periods:
        vals = [(i, rows[i].get(f'ER@{per}')) for i in range(n_rows)]
        valid = sorted([(i, v) for i, v in vals if not pd.isna(v)], key=lambda x: x[1])
        m = len(valid)
        for rank, (i, _) in enumerate(valid):
            rows[i][f'pct@{per}'] = (rank + 1) / m * 100 if m else float('nan')
        for i, v in vals:
            if pd.isna(v):
                rows[i][f'pct@{per}'] = float('nan')
    for c in rows:
        cells = [(p, c.get(f'pct@{p}')) for p in periods]
        cells = [(p, v) for p, v in cells if not pd.isna(v)]
        if cells:
            bp, bv = max(cells, key=lambda x: x[1])
            c['best_tf'], c['best_pct'] = bp, bv
            c['best_er'] = c.get(f'ER@{bp}')
        else:
            c['best_tf'], c['best_pct'], c['best_er'] = '—', float('nan'), float('nan')


def build_snapshot_digest(rows, meta, ctx, top_n=30):
    """Fixed-width multi-period export, written to be pasted into a chat.

    One row per position, one ER column per period, orientation fixed by the
    primary period. Everything an outside reader needs to judge whether a row is
    tradeable — span, bar, sample size, standard error, and whether the metric is
    inferential or descriptive at that span — sits in the header, so the numbers
    cannot be read out of context.
    """
    pers = list(meta['periods'])
    L = []
    A = L.append
    A("SAKATA MULTI-PERIOD SNAPSHOT")
    A(f"generated   {datetime.now():%Y-%m-%d %H:%M}")
    A(f"universe    {ctx['universe']}")
    A(f"legs        {ctx['weighting']}   leg-ratio cap {ctx['ratio_cap']}")
    A(f"primary     {meta['primary']}  (orientation and sort are fixed by this period)")
    A("")
    A("-- PERIOD FRAME ------------------------------------------------------")
    A(f"{'per':<5}{'bar':<6}{'span':>7}{'bars':>7}{'SE':>8}   metric status at this span")
    for per in pers:
        m = meta['periods'][per]
        stat = ("Sharpe usable" if m['se'] <= 1.5 else
                "Sharpe marginal" if m['se'] <= 2.5 else "descriptive only (use ER)")
        A(f"{per:<5}{m['bar']:<6}{m['span']:>6}d{m['bars']:>7}{m['se']:>8.1f}   {stat}")
    A("")
    A("ER = Kaufman efficiency ratio on the equity curve: |net move| / path length.")
    A("    1.00 = straight line, 0.00 = chop going nowhere, negative = downtrend.")
    A("    Scale-free and descriptive, so it stays readable on short spans where")
    A("    Sharpe does not. ALIGN = periods with positive ER (persistence).")
    A("")
    A("Raw ER is NOT comparable across horizons — a coarser bar traces a shorter")
    A("    path, inflating ER mechanically. PCTILE is the position's rank WITHIN its")
    A("    own horizon, which IS comparable. BEST = the horizon to trade it on.")
    A("")
    prim = meta['primary']
    A("-- RANKED BY BEST CELL (position x horizon) ------------------------")
    hdr = f"{'#':>3} {'LONG':<6}{'SHORT':<6}{'SECTOR':<9}{'BEST':>5}{'PCT':>5}{'ALIGN':>6}"
    for per in pers:
        hdr += f"{'ER_' + per:>8}"
    hdr += f"{'SHRP':>8}{'TOT%':>8}{'VOL%':>8}{'MDD%':>8}{'CORR':>7}{'RATIO':>7}"
    A(hdr)
    for i, c in enumerate(rows[:top_n], 1):
        ln = 'cash' if c['long'] is None else SYMBOL_NAMES.get(c['long'], clean_symbol(c['long']))
        sn = 'cash' if c['short'] is None else SYMBOL_NAMES.get(c['short'], clean_symbol(c['short']))
        pc = c.get('best_pct')
        line = (f"{i:>3} {ln:<6}{sn:<6}{str(c.get('Sector','-'))[:8]:<9}"
                f"{str(c.get('best_tf','-')):>5}"
                f"{'   - ' if pd.isna(pc) else f'{pc:5.0f}'}"
                f"{c.get('align_txt','-'):>6}")
        for per in pers:
            v = c.get(f'ER@{per}')
            line += "     -  " if pd.isna(v) else f"{v:>8.3f}"
        cr = '     - ' if pd.isna(c['Corr']) else f"{c['Corr']:7.2f}"
        rt = '     - ' if pd.isna(c['Ratio']) else f"{c['Ratio']:7.2f}"
        line += (f"{c['Sharpe']:>8.2f}{c['Tot%']:>+8.2f}{c['Vol%']:>8.1f}"
                 f"{c['MDD%']:>8.2f}{cr}{rt}")
        A(line)

    A("")
    A("-- PERSISTENCE -------------------------------------------------------")
    n_all = sum(1 for c in rows if c.get('align') == c.get('align_n') and c.get('align_n'))
    A(f"positive ER in every period: {n_all} of {len(rows)} candidates")
    best = [c for c in rows if c.get('align') == c.get('align_n') and c.get('align_n')][:8]
    if best:
        A("  " + ",  ".join(
            ('cash' if c['long'] is None else SYMBOL_NAMES.get(c['long'], clean_symbol(c['long'])))
            + "/" +
            ('cash' if c['short'] is None else SYMBOL_NAMES.get(c['short'], clean_symbol(c['short'])))
            for c in best))
    lg, sh = leg_frequency(rows, 20)
    if sh or lg:
        A("")
        A("-- LEG CONCENTRATION, TOP 20 -----------------------------------------")
        A("short: " + "  ".join(f"{SYMBOL_NAMES.get(k, clean_symbol(k))}x{v}"
                                for k, v in sh.most_common(6)))
        A("long:  " + "  ".join(f"{SYMBOL_NAMES.get(k, clean_symbol(k))}x{v}"
                                for k, v in lg.most_common(6)))
        A("(one ticker dominating the short column means the field is one macro")
        A(" bet replicated, not N independent candidates)")
    rep = meta.get('report', {})
    if rep.get('dropped'):
        A("")
        A("dropped for thin coverage: " + ", ".join(
            SYMBOL_NAMES.get(x, clean_symbol(x)) for x in rep['dropped']))
    return "\n".join(L)


# =============================================================================
# COMBINED TABLE
# =============================================================================

def render_field_table(cands, theme, mode='equal', top_n=50):
    """One table, outrights and pairs interleaved by rank. Outrights sit on a
    tinted row with 'cash' in the SHORT column, so how high the plain longs are
    sitting is visible without cross-referencing a second table."""
    show = cands[:top_n]
    pos_c = theme['pos']; neg_c = theme['neg']; short_c = theme['short']
    _bg3 = theme.get('bg3', '#f8fafc')
    _txt2 = theme.get('text2', '#64748b'); _mut = theme.get('muted', '#94a3b8')
    _bdr = theme.get('border', '#e2e8f0')
    th = (f"padding:4px 8px;border-bottom:1px solid {_bdr};color:#475569;"
          "font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:0.06em;")
    td = f"padding:5px 8px;border-bottom:1px solid {_bdr}22;"

    ratio_hdr = {'vol': 'σ RATIO', 'beta': 'BETA'}.get(mode, 'RATIO')
    html = f"""<div style='overflow-x:auto;border:1px solid {_bdr};border-radius:6px'><table style='border-collapse:collapse;font-family:{FONTS};font-size:11px;width:100%;line-height:1.3'>
        <thead style='background:{_bg3}'><tr>
            <th style='{th}text-align:left'>#</th>
            <th style='{th}text-align:left'>LONG</th>
            <th style='{th}text-align:left'>SHORT</th>
            <th style='{th}text-align:left'>SECTOR</th>
            <th style='{th}text-align:right'>{ratio_hdr}</th>
            <th style='{th}text-align:right'>SCORE</th>
            <th style='{th}text-align:right'>SHARPE</th>
            <th style='{th}text-align:right'>SORTINO</th>
            <th style='{th}text-align:right'>MAR</th>
            <th style='{th}text-align:right'>R²</th>
            <th style='{th}text-align:right'>ER</th>
            <th style='{th}text-align:right'>WIN%</th>
            <th style='{th}text-align:right'>TOT%</th>
            <th style='{th}text-align:right'>VOL%</th>
            <th style='{th}text-align:right'>MDD%</th>
            <th style='{th}text-align:right'>CORR</th>
        </tr></thead><tbody>"""

    for rank, p in enumerate(show, 1):
        is_out = p['kind'] == 'outright'
        cash = f"<span style='color:{_mut};font-style:italic'>cash</span>"
        ln = (cash if p['long'] is None
              else SYMBOL_NAMES.get(p['long'], clean_symbol(p['long'])))
        sn = (cash if p['short'] is None
              else SYMBOL_NAMES.get(p['short'], clean_symbol(p['short'])))
        sh_c = pos_c if p['Sharpe'] >= 0 else neg_c
        tot_c = pos_c if p['Tot%'] >= 0 else neg_c
        tot_s = '+' if p['Tot%'] >= 0 else ''
        win_c = pos_c if p['Win%'] >= 55 else (neg_c if p['Win%'] < 45 else _txt2)
        er_c = pos_c if p['ER'] >= 0.30 else (_txt2 if p['ER'] >= 0.12 else _mut)
        score = p.get('_score', 0)
        corr = '—' if pd.isna(p['Corr']) else f"{p['Corr']:.2f}"
        if pd.isna(p['Ratio']):
            ratio = '—'
        else:
            hot = abs(p['Ratio']) > RATIO_WARN or abs(p['Ratio']) < 1 / RATIO_WARN
            ratio = (f"<span style='color:{neg_c}'>{p['Ratio']:.2f}⚠</span>" if hot
                     else f"{p['Ratio']:.2f}")
        bg = f'linear-gradient(90deg,{_bg3},{_bg3}00)' if is_out else 'transparent'
        short_style = f"color:{_mut}" if is_out else f"color:{short_c};font-weight:600"
        sec_c = _txt2 if p.get('same_sector') else _mut
        html += f"""<tr style='background:{bg}'>
            <td style='{td}color:{_mut};text-align:left'>{rank}</td>
            <td style='{td}color:{pos_c};font-weight:600;text-align:left'>{ln}</td>
            <td style='{td}{short_style};text-align:left'>{sn}</td>
            <td style='{td}color:{sec_c};text-align:left;font-size:10px'>{p.get('Sector','—')}</td>
            <td style='{td}text-align:right;color:{_txt2}'>{ratio}</td>
            <td style='{td}text-align:right;color:{_txt2};font-weight:600'>{score:.1f}</td>
            <td style='{td}text-align:right'><span style='color:{sh_c};font-weight:700'>{p["Sharpe"]:.2f}</span></td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["Sortino"]:.2f}</td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["MAR"]:.2f}</td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["R²"]:.3f}</td>
            <td style='{td}text-align:right'><span style='color:{er_c};font-weight:600'>{p["ER"]:.3f}</span></td>
            <td style='{td}text-align:right'><span style='color:{win_c};font-weight:600'>{p["Win%"]:.0f}%</span></td>
            <td style='{td}text-align:right'><span style='color:{tot_c};font-weight:600'>{tot_s}{p["Tot%"]:.1f}%</span></td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["Vol%"]:.1f}%</td>
            <td style='{td}text-align:right;color:{neg_c}'>{p["MDD%"]:.1f}%</td>
            <td style='{td}text-align:right;color:{_txt2}'>{corr}</td>
        </tr>"""
    html += "</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)


# =============================================================================
# CHART RENDERER
# =============================================================================

def _tick_fmt(index):
    """Short axis labels. A 10-day hourly window still wants day labels, not
    'DD Mon HH:MM' on every tick — long strings collide with the right axis."""
    span_h = (index[-1] - index[0]).total_seconds() / 3600
    if span_h <= 30:
        return '%H:%M'
    if span_h <= 72:
        return '%d %b %H:%M'
    return '%d %b'


def render_spread_charts(pairs, data, theme, mobile=False, tick_fmt='%d %b',
                         max_charts=6, bar_tag=''):
    top_n = min(max_charts, len(pairs))
    if top_n == 0:
        return

    _pbg = theme.get('plot_bg', '#ffffff'); _grd = theme.get('grid', '#eef2f6')
    _axl = theme.get('axis_line', '#e2e8f0'); _tk = theme.get('tick', '#94a3b8')
    _mut = theme.get('muted', '#94a3b8')

    n_cols = 1 if mobile else min(3, top_n)
    n_rows = (top_n + n_cols - 1) // n_cols

    subtitles = []
    for i in range(top_n):
        p = pairs[i]
        ln = SYMBOL_NAMES.get(p['long'], clean_symbol(p['long']))
        lc = theme['long']; sc = theme['short']
        tag = (f"<span style='color:{_mut};font-size:9px'> · {bar_tag}</span>"
               if bar_tag else "")
        if p['kind'] == 'outright':
            sym = SYMBOL_NAMES.get(p.get('sym'), clean_symbol(p.get('sym', '')))
            d = p.get('dir', 'long')
            col = lc if d == 'long' else sc
            subtitles.append(f"<span style='color:{col}'>■</span> {d} {sym}{tag}")
        else:
            sn = SYMBOL_NAMES.get(p['short'], clean_symbol(p['short']))
            subtitles.append(
                f"<span style='color:{lc}'>■</span> {ln}  "
                f"<span style='color:{sc}'>■</span> {sn}  "
                f"<span style='color:#0f172a'>■</span> Spread{tag}")
    while len(subtitles) < n_rows * n_cols:
        subtitles.append("")

    # vertical_spacing is a fraction of TOTAL figure height, so a fixed fraction
    # balloons into hundreds of px on tall grids. Work in pixels instead, then
    # respect plotly's 1/(rows-1) ceiling.
    chart_h = (350 if mobile else 220) * n_rows
    gap_px = 60 if mobile else 78
    v_space = min(gap_px / chart_h, 0.9 / max(n_rows - 1, 1))
    h_space = min(0.06, 0.8 / max(n_cols - 1, 1))
    fig = make_subplots(rows=n_rows, cols=n_cols, subplot_titles=subtitles,
                        horizontal_spacing=h_space, vertical_spacing=v_space)

    for i in range(top_n):
        p = pairs[i]; row = i // n_cols + 1; col = i % n_cols + 1
        fig.add_trace(go.Scatter(
            x=list(range(len(p['cum_long']))), y=p['cum_long'].values, mode='lines',
            line=dict(color=theme['long'], width=1.3, shape='spline', smoothing=1.0),
            showlegend=False, hovertemplate='Long: %{y:.1f}<extra></extra>'),
            row=row, col=col)
        if p['cum_short'] is not None:
            fig.add_trace(go.Scatter(
                x=list(range(len(p['cum_short']))), y=p['cum_short'].values, mode='lines',
                line=dict(color=theme['short'], width=1.3, shape='spline', smoothing=1.0),
                showlegend=False, hovertemplate='Short: %{y:.1f}<extra></extra>'),
                row=row, col=col)
            fig.add_trace(go.Scatter(
                x=list(range(len(p['cum_spread']))), y=p['cum_spread'].values, mode='lines',
                line=dict(color='#0f172a', width=1.5, dash='dot', shape='spline',
                          smoothing=1.0),
                showlegend=False, hovertemplate='Spread: %{y:.1f}<extra></extra>'),
                row=row, col=col)
        fig.add_hline(y=100, line=dict(color=_grd, width=0.8, dash='dot'),
                      row=row, col=col)

        axis_idx = (row - 1) * n_cols + col
        fig.add_annotation(
            text=f"<b>{i+1}</b>", x=0.02, y=0.95,
            xref=f"x{'' if axis_idx == 1 else axis_idx} domain",
            yref=f"y{'' if axis_idx == 1 else axis_idx} domain",
            showarrow=False, font=dict(size=12, color=_mut, family=FONTS),
            xanchor='left', yanchor='top')

        n_ticks = 3 if n_cols > 1 else 4
        idx_step = max(1, len(data) // n_ticks)
        tick_vals = list(range(0, len(data), idx_step))
        last = len(data) - 1
        # only pin the final bar if it is not sitting on the previous tick
        if last - tick_vals[-1] > idx_step * 0.5:
            tick_vals.append(last)
        else:
            tick_vals[-1] = last
        tick_text = [data.index[j].strftime(tick_fmt) for j in tick_vals if j < len(data)]
        tick_vals = tick_vals[:len(tick_text)]
        axis_key = 'xaxis' if axis_idx == 1 else f'xaxis{axis_idx}'
        fig.update_layout(**{axis_key: dict(tickmode='array', tickvals=tick_vals,
                                            ticktext=tick_text)})

    for ann in fig['layout']['annotations']:
        xref_str = str(ann['xref']) if ann['xref'] else ''
        if 'domain' not in xref_str:
            ann['font'] = dict(size=10, family=FONTS)

    fig.update_layout(
        template='plotly_white', height=chart_h,
        margin=dict(l=40, r=40, t=45, b=30),
        plot_bgcolor=_pbg, paper_bgcolor=_pbg,
        showlegend=False, hovermode='x unified', font=dict(family=FONTS))
    fig.update_xaxes(gridcolor=_grd, linecolor=_axl,
                     tickfont=dict(color=_tk, size=8, family=FONTS),
                     showgrid=False, tickangle=0)
    fig.update_yaxes(gridcolor=_grd, linecolor=_axl,
                     tickfont=dict(color=_tk, size=8, family=FONTS), side='right')

    st.plotly_chart(fig, use_container_width=True, config={
        'scrollZoom': True, 'displayModeBar': False, 'responsive': True})


# =============================================================================
# MAIN RENDER
# =============================================================================

def _badge(theme, bits):
    """Persistent context strip: window, bar size, sample, universe, weighting.
    Sits directly under the controls so the timeframe in force is never a
    guess."""
    _bdr = theme.get('border', '#e2e8f0'); _bg3 = theme.get('bg3', '#f8fafc')
    chips = "".join(
        f"<span style='display:inline-block;padding:3px 9px;margin:0 5px 5px 0;"
        f"border:1px solid {_bdr};border-radius:5px;background:{_bg3};"
        f"font-size:10.5px;font-weight:600;letter-spacing:0.03em;color:#475569;"
        f"font-variant-numeric:tabular-nums'>{b}</span>" for b in bits)
    st.markdown(f"<div style='margin:6px 0 10px'>{chips}</div>",
                unsafe_allow_html=True)


def render_snapshot_table(rows, meta, theme, top_n=40):
    """One row per position, one ER column per period."""
    pers = list(meta['periods'])
    pos_c = theme['pos']; neg_c = theme['neg']; short_c = theme['short']
    _bg3 = theme.get('bg3', '#f8fafc'); _bdr = theme.get('border', '#e2e8f0')
    _txt2 = theme.get('text2', '#64748b'); _mut = theme.get('muted', '#94a3b8')
    th = (f"padding:4px 7px;border-bottom:1px solid {_bdr};color:#475569;"
          "font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:0.05em;")
    td = f"padding:5px 7px;border-bottom:1px solid {_bdr}22;"

    def er_col(v):
        if pd.isna(v):
            return _mut
        if v >= 0.30:
            return pos_c
        if v >= 0.12:
            return _txt2
        return neg_c if v < 0 else _mut

    head = (f"<th style='{th}text-align:left'>#</th>"
            f"<th style='{th}text-align:left'>LONG</th>"
            f"<th style='{th}text-align:left'>SHORT</th>"
            f"<th style='{th}text-align:left'>SECTOR</th>"
            f"<th style='{th}text-align:center'>BEST</th>"
            f"<th style='{th}text-align:right'>PCTILE</th>"
            f"<th style='{th}text-align:center'>ALIGN</th>")
    for per in pers:
        mark = " ★" if per == meta['primary'] else ""
        head += f"<th style='{th}text-align:right'>ER {per}{mark}</th>"
    for c in ('SHARPE', 'TOT%', 'VOL%', 'MDD%', 'CORR', 'RATIO'):
        head += f"<th style='{th}text-align:right'>{c}</th>"

    html = (f"<div style='overflow-x:auto;border:1px solid {_bdr};border-radius:6px'>"
            f"<table style='border-collapse:collapse;font-family:{FONTS};font-size:11px;"
            f"width:100%;line-height:1.3;font-variant-numeric:tabular-nums'>"
            f"<thead style='background:{_bg3}'><tr>{head}</tr></thead><tbody>")

    for i, c in enumerate(rows[:top_n], 1):
        cash = f"<span style='color:{_mut};font-style:italic'>cash</span>"
        ln = cash if c['long'] is None else SYMBOL_NAMES.get(c['long'], clean_symbol(c['long']))
        sn = cash if c['short'] is None else SYMBOL_NAMES.get(c['short'], clean_symbol(c['short']))
        is_out = c['kind'] == 'outright'
        bg = f'linear-gradient(90deg,{_bg3},{_bg3}00)' if is_out else 'transparent'
        full = c.get('align_n') and c['align'] == c['align_n']
        al_c = pos_c if full else (_txt2 if c.get('align', 0) else _mut)
        row = (f"<tr style='background:{bg}'>"
               f"<td style='{td}color:{_mut}'>{i}</td>"
               f"<td style='{td}color:{pos_c};font-weight:600'>{ln}</td>"
               f"<td style='{td}color:{short_c};font-weight:600'>{sn}</td>"
               f"<td style='{td}color:{_mut};font-size:10px'>{c.get('Sector','—')}</td>")
        pc = c.get('best_pct')
        pc_c = pos_c if not pd.isna(pc) and pc >= 90 else (
            _txt2 if not pd.isna(pc) and pc >= 70 else _mut)
        row += (f"<td style='{td}text-align:center;color:{pos_c};font-weight:700'>"
                f"{c.get('best_tf','—')}</td>"
                f"<td style='{td}text-align:right;color:{pc_c};font-weight:700'>"
                f"{'—' if pd.isna(pc) else f'{pc:.0f}'}</td>"
                f"<td style='{td}text-align:center;color:{al_c}'>"
                f"{c.get('align_txt','—')}</td>")
        for per in pers:
            v = c.get(f'ER@{per}')
            txt = '—' if pd.isna(v) else f"{v:.3f}"
            wt = '700' if per == meta['primary'] else '500'
            row += (f"<td style='{td}text-align:right;color:{er_col(v)};"
                    f"font-weight:{wt}'>{txt}</td>")
        tot_c = pos_c if c['Tot%'] >= 0 else neg_c
        cr = '—' if pd.isna(c['Corr']) else f"{c['Corr']:.2f}"
        rt = '—' if pd.isna(c['Ratio']) else f"{c['Ratio']:.2f}"
        row += (f"<td style='{td}text-align:right;color:{_txt2}'>{c['Sharpe']:.2f}</td>"
                f"<td style='{td}text-align:right;color:{tot_c};font-weight:600'>{c['Tot%']:+.1f}%</td>"
                f"<td style='{td}text-align:right;color:{_txt2}'>{c['Vol%']:.1f}%</td>"
                f"<td style='{td}text-align:right;color:{neg_c}'>{c['MDD%']:.1f}%</td>"
                f"<td style='{td}text-align:right;color:{_txt2}'>{cr}</td>"
                f"<td style='{td}text-align:right;color:{_txt2}'>{rt}</td></tr>")
        html += row
    html += "</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)


def _render_snapshot_mode(theme, is_mobile):
    st.caption(
        "Every position measured across the whole calendar ladder at once — "
        "intraday, week, month, quarter, year — from a single 1-hour pull "
        "resampled five ways. Orientation is fixed by the primary period so the "
        "columns are comparable. **ALIGN** counts periods with positive ER: a "
        "position trending cleanly on the quarter *and* the month *and* the week "
        "is a far stronger claim than any one window."
    )
    c1, c2, c3, c4, c5 = st.columns([2, 3, 2, 2, 1])
    with c1:
        st.markdown("##### Primary period")
        primary = st.selectbox("Primary", list(PERIOD_BARS), index=2,
                               key="snap_prim", label_visibility="collapsed")
    with c2:
        st.markdown("##### Universe")
        universe = st.selectbox("Universe", universe_options(), index=0,
                                key="snap_univ", label_visibility="collapsed")
    with c3:
        st.markdown("##### Leg weighting")
        weight_label = st.selectbox("Weighting", list(WEIGHTINGS), index=1,
                                    key="snap_w", label_visibility="collapsed")
    with c4:
        st.markdown("##### Max leg ratio")
        cap_label = st.selectbox("Cap", list(RATIO_CAPS), index=2,
                                 key="snap_cap", label_visibility="collapsed")
    with c5:
        st.markdown("##### Show")
        show = st.selectbox("Show", ["20", "40", "80", "All"], index=1,
                            key="snap_show", label_visibility="collapsed")

    if st.button("Refresh", key="snap_rs"):
        fetch_spread_data.clear()
        build_snapshot.clear()
        st.rerun()

    mode = WEIGHTINGS[weight_label]
    with st.spinner("Building ladder — one 1-hour pull, resampled five ways…"):
        rows, meta = build_snapshot(tuple(ALL_SYMBOLS), primary, mode, universe)

    if not rows:
        st.warning("Snapshot unavailable — "
                   f"{meta.get('error', 'no data returned')}. Try Refresh.")
        return

    cap = RATIO_CAPS[cap_label]
    n_capped = 0
    if cap and mode != 'equal':
        keep = [c for c in rows if c['kind'] == 'outright' or
                (not pd.isna(c['Ratio']) and (1 / cap) <= abs(c['Ratio']) <= cap)]
        n_capped = len(rows) - len(keep)
        rows = keep

    prim = meta['primary']
    pers = list(meta['periods'])
    score_cells(rows, pers)
    rows = sorted(rows, key=lambda c: -(c.get('best_pct')
                                        if not pd.isna(c.get('best_pct', float('nan')))
                                        else -1))

    _badge(theme, [f"primary {prim} · {PERIOD_BARS[prim]}"]
           + [f"{p} {m['bar']} · {m['bars']}b · SE ±{m['se']:.1f}"
              for p, m in meta['periods'].items()]
           + [universe, f"legs: {weight_label}"])

    n_out = sum(1 for c in rows if c['kind'] == 'outright')
    n_full = sum(1 for c in rows if c.get('align_n') and c['align'] == c['align_n'])
    owners = {}
    for c in rows:
        owners[c.get('best_tf', '—')] = owners.get(c.get('best_tf', '—'), 0) + 1
    own_txt = " · ".join(f"{k} {v}" for k, v in
                        sorted(owners.items(), key=lambda x: -x[1]) if k != '—')
    st.markdown(
        f"**{len(rows)} candidates** ({n_out} outrights) · sorted by **best cell** "
        f"— the horizon each position ranks highest on"
        + (f" · {n_capped} hidden by the {cap_label} leg-ratio cap" if n_capped else ""))
    st.caption(
        f"**Horizon ownership:** {own_txt}. "
        f"PCTILE is the rank *within* that horizon, so it is comparable across "
        f"columns — raw ER is not, because a coarser bar traces a shorter path and "
        f"inflates ER mechanically. ALIGN ({n_full} positive on every horizon) is "
        f"kept as context, not as the objective: you are choosing a cell, not "
        f"stacking confirmations."
        + (" Note MTD and QTD share a start date in the first month of a quarter, "
           "so the split between them is arbitrary until the month turns."
           if {'MTD', 'QTD'} <= set(pers) and
           period_start('MTD') == period_start('QTD') else ""))

    top_n = len(rows) if show == "All" else int(show)
    st.markdown(f"##### Ladder — {min(top_n, len(rows))} of {len(rows)} · ★ = primary")
    render_snapshot_table(rows, meta, theme, top_n=top_n)

    with st.expander("📋 Copy digest — paste this for analysis", expanded=True):
        st.caption("Fixed-width export carrying the period frame, standard errors, "
                   "and persistence counts alongside the numbers, so the table "
                   "cannot be read out of context. Copy button sits top-right.")
        dn = st.slider("Rows", 10, 80, 30, 5, key="snap_dgn")
        ctx = {'universe': universe, 'weighting': weight_label,
               'ratio_cap': cap_label}
        st.code(build_snapshot_digest(rows, meta, ctx, top_n=dn), language='text')


def render_spreads_tab(is_mobile: bool = False) -> None:
    theme = THEMES.get(st.session_state.get("theme", "Light"), THEMES["Dark"])

    view = st.radio("View", ["Single period — full field", "Snapshot — all horizons"],
                    index=0, horizontal=True, key="spr_view",
                    label_visibility="collapsed")
    if view.startswith("Snapshot"):
        _render_snapshot_mode(theme, is_mobile)
        return

    n_inst = len(ALL_SYMBOLS)
    st.caption(
        f"Outrights and long/short pairs ranked in **one field** — {n_inst} "
        f"outrights plus {n_inst * (n_inst - 1) // 2} pairs, measured identically. "
        "Outrights sit in the same table on tinted rows against *cash*, so where "
        "they land IS the answer to whether spreading is worth it. Sign is "
        "auto-flipped so LONG is the leg to be long. Calendar periods carry a "
        "matched bar size (WTD·1H, MTD·4H, QTD·1D, YTD·1W); the bar steps finer "
        "automatically if a window comes back thin."
    )

    r1c1, r1c2, r1c3, r1c4 = st.columns([2, 2, 3, 2])
    with r1c1:
        st.markdown("##### Lookback")
        lb_label = st.selectbox("Lookback", LOOKBACK_OPTIONS, index=1,
                                key="spr_lookback", label_visibility="collapsed")
    with r1c2:
        st.markdown("##### Bars")
        bar_label = st.selectbox("Bars", list(BAR_OPTIONS), index=0, key="spr_bars",
                                 label_visibility="collapsed")
    with r1c3:
        st.markdown("##### Universe")
        universe = st.selectbox("Universe", universe_options(), index=0,
                                key="spr_universe", label_visibility="collapsed")
    with r1c4:
        st.markdown("##### Leg weighting")
        weight_label = st.selectbox("Weighting", list(WEIGHTINGS), index=0,
                                    key="spr_weight", label_visibility="collapsed")

    r2c1, r2c2, r2c5, r2c3, r2c4 = st.columns([2, 2, 2, 1, 1])
    with r2c1:
        st.markdown("##### Fitness")
        sort_by = st.selectbox("Fitness", list(SORT_KEYS), index=0, key="spr_sort",
                               label_visibility="collapsed")
    with r2c2:
        st.markdown("##### Include")
        type_filter = st.selectbox("Include", TYPE_FILTERS, index=0, key="spr_type",
                                   label_visibility="collapsed")
    with r2c5:
        st.markdown("##### Max leg ratio")
        cap_label = st.selectbox("Max leg ratio", list(RATIO_CAPS), index=2,
                                 key="spr_cap", label_visibility="collapsed")
    with r2c3:
        st.markdown("##### Show")
        show = st.selectbox("Show", ["10", "25", "50", "100", "All"], index=4,
                            key="spr_topn", label_visibility="collapsed")
    with r2c4:
        st.markdown("##### Charts")
        n_charts = st.selectbox("Charts", [6, 12, 20, 30, 48], index=2,
                                key="spr_charts", label_visibility="collapsed")

    if st.button("Refresh", key="rs"):
        fetch_spread_data.clear()
        st.rerun()

    mode = WEIGHTINGS[weight_label]
    symbols = ALL_SYMBOLS

    # --- resolve window and bar size ---
    is_period = lb_label in PERIOD_BARS
    if is_period:
        start_dt = period_start(lb_label)
        start_iso = start_dt.isoformat()
        lb_days = 0
        default_interval = PERIOD_BARS[lb_label]
        window_days = max((datetime.now() - start_dt).days, 1)
        window_txt = f"{lb_label} · from {start_dt:%d %b %Y}"
    else:
        start_iso = None
        lb_days = ROLLING_DAYS[lb_label]
        default_interval = auto_interval(lb_days)
        window_days = lb_days
        window_txt = lb_label

    requested = BAR_OPTIONS[bar_label] or default_interval
    pinned = BAR_OPTIONS[bar_label] is not None

    # --- fetch, stepping finer if the window comes back thin ---
    tried, res, iv = [], None, requested
    while iv is not None:
        cap = _MAX_BACK.get(iv)
        if cap is not None and window_days > cap:
            tried.append((iv, 'beyond Yahoo history limit'))
            iv = _FINER.get(iv)
            continue
        with st.spinner(f"Pricing {len(symbols)} instruments on "
                        f"{BAR_NAMES[iv]} bars…"):
            res = fetch_spread_data(tuple(symbols), lb_days, iv, start_iso)
        n_rows = 0 if res['data'] is None else len(res['data'])
        tried.append((iv, f"{n_rows} bars"))
        if n_rows >= MIN_BARS or pinned:
            break
        iv = _FINER.get(iv)
    interval = iv or requested
    bar_name = BAR_NAMES[interval]
    bar_tag = BAR_SHORT[interval]

    def _diagnostics(r):
        with st.expander("Data coverage — why this window looks the way it does"):
            if tried:
                st.markdown("**Bar sizes tried:** " +
                            "  →  ".join(f"{BAR_NAMES[i]} ({m})" for i, m in tried))
            if r.get('dropped'):
                st.markdown(
                    "**Dropped for thin coverage:** " +
                    ", ".join(f"{SYMBOL_NAMES.get(s, clean_symbol(s))} "
                              f"({r['cov'].get(s, 0):.0%})" for s in r['dropped']) +
                    "  — shed so the remaining instruments keep their full history, "
                    "rather than every symbol being clipped to the sparsest one.")
            if r.get('cov'):
                cdf = pd.DataFrame({
                    'Instrument': [SYMBOL_NAMES.get(s, clean_symbol(s)) for s in r['cov']],
                    'Sector': [_sector_of(s) for s in r['cov']],
                    'Raw bars': [r['raw'].get(s, 0) for s in r['cov']],
                    'Coverage': [f"{v:.0%}" for v in r['cov'].values()],
                    'Kept': ['—' if s in r.get('dropped', []) else '✓' for s in r['cov']],
                }).sort_values('Coverage')
                st.dataframe(cdf, use_container_width=True, hide_index=True)

    if res is None or res['data'] is None:
        _badge(theme, [window_txt, f"{bar_name} bars", "no usable data"])
        st.warning(
            f"Not enough usable history over {window_txt} on {bar_name} bars. "
            + ("You've pinned the bar size — set Bars back to Auto to let it step "
               "finer automatically. " if pinned else "Every finer bar was tried too. ")
            + "Open the panel below to see which instruments came back thin.")
        _diagnostics(res or {'raw': {}, 'cov': {}, 'dropped': []})
        return

    data = res['data']
    ann = ann_factor_for(data.index)

    outs = compute_outrights(data, ann, allow_short=True)
    pairs = compute_pairs(data, ann, mode)
    outs, pairs = filter_universe(outs, pairs, universe)

    # Drop sizings that cannot be executed. A sigma ratio of 46 is not a spread.
    cap = RATIO_CAPS[cap_label]
    n_capped = 0
    if cap and mode != 'equal':
        keep = [p for p in pairs
                if not pd.isna(p['Ratio']) and (1 / cap) <= abs(p['Ratio']) <= cap]
        n_capped = len(pairs) - len(keep)
        pairs = keep
    if not outs and not pairs:
        st.info("Nothing in that universe over this window.")
        return

    # --- rank outrights and pairs in ONE field ---
    field = outs + pairs
    rank_field(field)
    apply_field_rank(field, sort_by)
    metric_txt = sort_by

    _badge(theme, [
        window_txt,
        f"{bar_name} bars · {len(data)} obs",
        f"annualised ×{ann:,.0f}",
        f"{len(data.columns)} instruments",
        universe,
        f"legs: {weight_label}",
        f"fitness: {metric_txt}",
    ])

    best_out = min(outs, key=lambda c: c['_field']) if outs else None
    best_pair = min(pairs, key=lambda c: c['_field']) if pairs else None
    n_beat = sum(1 for p in pairs if best_out and p['_field'] < best_out['_field'])
    top10 = sorted(field, key=lambda c: c['_field'])[:10]
    outs_top10 = sum(1 for c in top10 if c['kind'] == 'outright')

    line = [f"**{len(outs)} outrights + {len(pairs)} pairs** = {len(field)} candidates"]
    if best_out:
        bo = SYMBOL_NAMES.get(best_out['long'], clean_symbol(best_out['long']))
        line.append(f"best outright **{bo}** at #{best_out['_field']}")
    if best_pair:
        bl = SYMBOL_NAMES.get(best_pair['long'], clean_symbol(best_pair['long']))
        bs = SYMBOL_NAMES.get(best_pair['short'], clean_symbol(best_pair['short']))
        line.append(f"best pair **{bl}/{bs}** at #{best_pair['_field']}")
    if best_out and pairs:
        line.append(f"**{n_beat} of {len(pairs)}** pairs beat it")
        line.append(f"**{outs_top10}/10** of the top ten are outrights")
    st.markdown("  ·  ".join(line))

    if outs and pairs:
        se_ = (ann / len(data)) ** 0.5
        mp = float(np.median([c['Sharpe'] for c in pairs]))
        mo = float(np.median([c['Sharpe'] for c in outs]))
        st.caption(
            f"Median Sharpe — pairs **{mp:.2f}**, outrights **{mo:.2f}** "
            f"(standard error ±{se_:.2f}). Best pair is "
            f"**{best_pair['Sharpe'] / se_:.2f} SE** from zero, best outright "
            f"**{best_out['Sharpe'] / se_:.2f} SE**. Comparing the two *best* "
            f"favours pairs simply because there are {len(pairs)} of them against "
            f"{len(outs)} outrights — more draws, higher maximum. The medians are "
            f"the like-for-like comparison."
            + (f" {n_capped} pairs hidden by the {cap_label} leg-ratio cap."
               if n_capped else ""))

    st.caption(f"**{weight_label}** — {WEIGHT_BLURB[mode]}")

    if interval != requested:
        st.info(f"{BAR_NAMES[requested]} bars gave too few observations over "
                f"{window_txt} — stepped down to **{bar_name}**. Pin a bar in the "
                f"Bars selector to override.")

    # --- period progress: how full the sample is, and how full it will get ---
    prog = period_progress(lb_label, data) if is_period else None
    if prog:
        st.markdown(
            f"**{lb_label} is {prog['frac']:.0%} elapsed** — day "
            f"{prog['elapsed_days']} of {prog['total_days']}, closing "
            f"{prog['ends']:%a %d %b}. {prog['bars_now']} bars now, about "
            f"{prog['bars_proj']} by the close. Sharpe SE ±{prog['se_now']:.1f} "
            f"today, ±{prog['se_end']:.1f} at period end.")

    # --- is the chosen fitness function supportable over this span? ---
    verdict, se_span, msg = fitness_advice(window_days, sort_by)
    (st.error if verdict == 'bad' else st.warning if verdict == 'warn'
     else st.success)(msg)
    if verdict != 'ok':
        st.caption(
            f"{len(field)} candidates were tested on {len(data)} bars. With "
            f"SE ±{se_span:.1f}, the expected best-of-{len(field)} Sharpe from "
            f"pure noise is roughly {se_span * 2.8:.0f} — treat anything below "
            f"that as unproven.")

    _diagnostics(res)

    # --- the single ranked table ---
    if type_filter == 'Pairs only':
        table_rows = [c for c in field if c['kind'] == 'pair']
    elif type_filter == 'Outrights only':
        table_rows = [c for c in field if c['kind'] == 'outright']
    else:
        table_rows = list(field)
    table_rows = sort_candidates(table_rows, sort_by)

    top_n = len(table_rows) if show == "All" else int(show)
    st.markdown(f"##### Ranked field — {min(top_n, len(table_rows))} of "
                f"{len(table_rows)} · {universe} · {bar_name} bars · by {metric_txt}")
    render_field_table(table_rows, theme, mode=mode, top_n=top_n)

    lg, sh = leg_frequency(table_rows, 20)
    if sh or lg:
        with st.expander("Leg concentration — is this one trade or twenty?"):
            st.caption(
                "How often each instrument appears in the top 20. When one ticker "
                "is the short leg of most of them, the field is a single macro bet "
                "replicated against whatever rallied, and the cleanest expression "
                "of it is the outright rather than the spreads.")
            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown("**Short legs**")
                for k, v in sh.most_common(8):
                    st.markdown(f"`{v:2}/20`  {SYMBOL_NAMES.get(k, clean_symbol(k))}")
            with cc2:
                st.markdown("**Long legs**")
                for k, v in lg.most_common(8):
                    st.markdown(f"`{v:2}/20`  {SYMBOL_NAMES.get(k, clean_symbol(k))}")

    drift = thesis_drift(data, table_rows, mode, top_n=12)
    if drift:
        broken = [d for d in drift if d['broken']]
        with st.expander(
                f"Thesis drift — when to stop the spread"
                + (f"  ·  {len(broken)} of {len(drift)} already broken" if broken else "")):
            st.caption(
                "Each top candidate re-measured on the first and second half of "
                "the window, orientation held fixed. The period boundary is your "
                "planned exit; a thesis break is the unplanned one and it comes "
                "first. Falling correlation shows why — when the legs stop moving "
                "together, the relationship the spread was built on is gone.")
            ddf = pd.DataFrame([{
                'Position': d['label'],
                'Sharpe H1': round(d['sh_h1'], 2),
                'Sharpe H2': round(d['sh_h2'], 2),
                'Δ': round(d['delta'], 2),
                'ER H1': round(d['er_h1'], 3),
                'ER H2': round(d['er_h2'], 3),
                'Corr H1': '—' if pd.isna(d['corr_h1']) else round(d['corr_h1'], 2),
                'Corr H2': '—' if pd.isna(d['corr_h2']) else round(d['corr_h2'], 2),
                'Status': 'BROKEN' if d['broken'] else ('fading' if d['delta'] < 0 else 'holding'),
            } for d in drift])
            st.dataframe(ddf, use_container_width=True, hide_index=True)
            if broken:
                st.warning(
                    "**" + ", ".join(d['label'] for d in broken) + "** turned "
                    "negative in the second half of the window. They rank well only "
                    "on first-half performance that has already reversed.")

    with st.expander("Copy digest — compact text export"):
        st.caption("Fixed-width summary sized to paste into a chat or notebook. "
                   "Keeps the diagnostics that decide whether any of this is real: "
                   "sample size, Sharpe standard error, outright-vs-pair verdict, "
                   "leg concentration. Use the copy button in the corner.")
        dg_n = st.slider("Rows in digest", 10, 60, 25, 5, key="spr_dgn")
        ctx = {'window': window_txt, 'bar': bar_name, 'ann': ann,
               'universe': universe, 'weighting': weight_label,
               'ratio_cap': cap_label, 'fitness': metric_txt,
               'n_out': len(outs), 'n_pair': len(pairs),
               'dropped': res.get('dropped', [])}
        st.code(build_digest(field, table_rows, data, ctx, top_n=dg_n),
                language='text')

    st.markdown(f"##### Top {min(n_charts, len(table_rows))} — legs vs spread, "
                f"rebased to 100 · {bar_name} bars")
    render_spread_charts(table_rows, data, theme, mobile=is_mobile,
                         max_charts=n_charts, tick_fmt=_tick_fmt(data.index),
                         bar_tag=bar_tag)
