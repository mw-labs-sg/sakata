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

from sakata_config import ALL_SYMBOLS, THEMES, SYMBOL_NAMES, FONTS, clean_symbol

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

    1.0 = a perfectly straight line, 0.0 = pure chop that goes nowhere.
    Signed so a smooth DOWNtrend scores -1.0 rather than +1.0. Unlike R² this
    is scale-free and makes no linearity assumption — it only asks how much of
    the distance travelled was actually retained.
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
    """Every metric for one return stream. Used for outrights AND pairs, so the
    two are measured identically and can be ranked in a single field."""
    mdd, add = _drawdowns(returns)
    ann = float(returns.mean() * ann_factor * 100)
    return {
        'Sharpe': _sharpe(returns, ann_factor),
        'Sortino': _sortino(returns, ann_factor),
        'MAR': float(ann / abs(add)) if add != 0 else 0.0,
        'R²': _r2(returns),
        'ER': _efficiency(returns),
        'Tot%': float(((1 + returns).cumprod().iloc[-1] - 1) * 100),
        'Ann%': ann,
        'Vol%': float(returns.std() * np.sqrt(ann_factor) * 100),
        'MDD%': mdd, 'ADD%': add,
        'Win%': float((returns > 0).sum() / len(returns) * 100) if len(returns) else 50.0,
    }


# =============================================================================
# LOOKBACK PERIODS AND BARS
# =============================================================================

# Calendar-anchored periods -> the bar size each one defaults to. These are
# anchors, not rolling windows: QTD on 1 July is 1 day long, not 90.
PERIOD_BARS = {'WTD': '1h', 'MTD': '4h', 'QTD': '1d', 'YTD': '1wk'}

# Rolling windows, kept for finer-grained work.
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
BAR_NAMES = {'15m': '15-minute', '30m': '30-minute', '1h': 'hourly',
             '4h': '4-hour', '1d': 'daily', '1wk': 'weekly'}

# rolling lookback (days) -> bar size, coarsening as the window widens.
_LADDER = ((2, '15m'), (7, '30m'), (20, '1h'), (60, '4h'))


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
    if period == 'WTD':
        return now - _dt.timedelta(days=now.weekday())      # Monday
    if period == 'MTD':
        return now.replace(day=1)
    if period == 'QTD':
        return now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1)
    if period == 'YTD':
        return now.replace(month=1, day=1)
    return None


def ann_factor_for(index):
    """Bars per year, measured off the data rather than assumed.

    Self-calibrating: a year of daily closes gives ~252, a 30-day window of 4h
    bars gives ~1500, weekly gives ~52. Keeps Sharpe/Sortino/vol comparable
    across bar types.
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

MIN_BARS = 20        # below this a window is not worth ranking 171 candidates on
MIN_SYMBOLS = 8      # never thin the universe past this to chase bar count

# coarse -> fine, for automatic bar-size fallback
_FINER = {'1wk': '1d', '1d': '4h', '4h': '1h', '1h': '30m', '30m': '15m', '15m': None}


def _align_frames(frames, intraday, min_bars=MIN_BARS, min_symbols=MIN_SYMBOLS):
    """Align a dict of {symbol: close Series} into one matrix.

    The old behaviour dropped ROWS: an inner join across all symbols, or ffill
    then dropna. Either way a single sparsely-listed contract governs the whole
    matrix — ffill cannot backfill a late listing, so dropna then deletes every
    row before it, and on intraday the intersection collapses to whichever
    market trades the fewest hours. Both were observed to cut a 31-week window
    to 6 rows and a 73-hour window to 9.

    So drop COLUMNS instead: rank symbols by how much of the union index they
    actually cover, and shed the worst until the matrix clears min_bars or the
    universe hits min_symbols. Returns (df, dropped, coverage).
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
    takes precedence over lookback_days.

    Returns {'data', 'raw', 'cov', 'dropped', 'interval'} — never a bare None,
    so the caller can explain WHY a window came back empty.
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
    if cap:   # respect Yahoo's per-interval history limit
        start = max(start, datetime.now() - pd.Timedelta(days=cap))

    # Fetch a few days before the anchor so a weekly/daily bar straddling the
    # boundary is not clipped off, then trim back to the anchor after aligning.
    fetch_start = start - pd.Timedelta(days=10 if interval in ('1wk', '1d') else 2)

    frames, raw = {}, {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym, session=_session)
            hist = ticker.history(start=fetch_start.strftime('%Y-%m-%d'),
                                  interval=yf_interval)
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
# CANDIDATE CONSTRUCTION — outrights and pairs, measured the same way
# =============================================================================

METRICS = ['Sharpe', 'Sortino', 'MAR', 'R²', 'ER']


def compute_outrights(data, ann_factor=252):
    """Every single instrument as a standalone long. The benchmark field."""
    out = []
    for sym in data.columns:
        ret = data[sym].pct_change().dropna()
        if len(ret) < 5:
            continue
        row = series_stats(ret, ann_factor)
        row.update({'long': sym, 'short': None, 'kind': 'outright',
                    'Corr': float('nan'), 'cum_long': data[sym],
                    'cum_short': None, 'cum_spread': data[sym]})
        out.append(row)
    return out


def compute_pairs(data, ann_factor=252):
    """Every long/short combination, sign-oriented so Sharpe reads positive."""
    pairs = []
    for s1, s2 in combinations(data.columns.tolist(), 2):
        r1 = data[s1].pct_change().dropna()
        r2 = data[s2].pct_change().dropna()
        spread_ret = (r1 - r2).dropna()
        if len(spread_ret) < 5:
            continue

        # Orient on Sharpe, then recompute EVERYTHING on the oriented series.
        # Negating Sortino/ER/R² directly is wrong: reversing the series turns
        # the old upside into the new downside, so the denominators change.
        if _sharpe(spread_ret, ann_factor) < 0:
            spread_ret = -spread_ret
            s1, s2 = s2, s1

        row = series_stats(spread_ret, ann_factor)

        cum_sp = pd.Series(100.0, index=data.index[:1])
        cum_sp = pd.concat([cum_sp, 100 * (1 + spread_ret).cumprod()])
        cum_sp = cum_sp[~cum_sp.index.duplicated(keep='last')]

        row.update({'long': s1, 'short': s2, 'kind': 'pair',
                    'Corr': float(r1.corr(r2)),
                    'cum_long': data[s1], 'cum_short': data[s2],
                    'cum_spread': cum_sp})
        pairs.append(row)
    return pairs


# =============================================================================
# RANKING — one combined field so "is the pair better?" has an answer
# =============================================================================

SORT_KEYS = {
    'Composite': '_score', 'Sharpe': 'Sharpe', 'Sortino': 'Sortino',
    'MAR': 'MAR', 'R² (linearity)': 'R²', 'ER (efficiency)': 'ER',
    'Total': 'Tot%', 'Win Rate': 'Win%',
}
LOWER_IS_BETTER = ('_score',)


def rank_field(candidates):
    """Rank outrights and pairs together on every metric, then average the
    ranks into a composite. Because both sides sit in one pool, an outright
    landing at composite rank 3 of 190 is a direct statement that spreading
    added nothing over that window."""
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
    """Position of each candidate in the combined field on the chosen fitness."""
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


def fitness_of(c, key):
    return c.get(key, 0)


# =============================================================================
# TABLE RENDERERS
# =============================================================================

def _table_shell(theme):
    _bdr = theme.get('border', '#e2e8f0')
    th = (f"padding:4px 8px;border-bottom:1px solid {_bdr};color:#475569;"
          "font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:0.06em;")
    td = f"padding:5px 8px;border-bottom:1px solid {_bdr}22;"
    return th, td, _bdr


def render_outright_table(outs, theme, key, top_n=25):
    """The benchmark leaderboard: every instrument as a plain long."""
    pos_c = theme['pos']; neg_c = theme['neg']
    _bg3 = theme.get('bg3', '#f8fafc')
    _txt2 = theme.get('text2', '#64748b'); _mut = theme.get('muted', '#94a3b8')
    th, td, _bdr = _table_shell(theme)

    cols = ['RANK', 'FIELD #', 'INSTRUMENT', 'SCORE', 'SHARPE', 'SORTINO', 'MAR',
            'R²', 'ER', 'WIN%', 'TOT%', 'VOL%', 'MDD%']
    head = ''.join(
        f"<th style='{th}text-align:{'left' if c in ('RANK', 'INSTRUMENT') else 'right'}'>{c}</th>"
        for c in cols)
    html = (f"<div style='overflow-x:auto;border:1px solid {_bdr};border-radius:6px'>"
            f"<table style='border-collapse:collapse;font-family:{FONTS};font-size:11px;"
            f"width:100%;line-height:1.3'><thead style='background:{_bg3}'><tr>{head}"
            "</tr></thead><tbody>")

    for rank, p in enumerate(outs[:top_n], 1):
        nm = SYMBOL_NAMES.get(p['long'], clean_symbol(p['long']))
        sh_c = pos_c if p['Sharpe'] >= 0 else neg_c
        tot_c = pos_c if p['Tot%'] >= 0 else neg_c
        tot_s = '+' if p['Tot%'] >= 0 else ''
        win_c = pos_c if p['Win%'] >= 55 else (neg_c if p['Win%'] < 45 else _txt2)
        er_c = pos_c if p['ER'] >= 0.30 else (_txt2 if p['ER'] >= 0.12 else _mut)
        score = p.get('_score', 0)
        html += f"""<tr>
            <td style='{td}color:{_mut};text-align:left'>{rank}</td>
            <td style='{td}color:{_txt2};text-align:right'>{p.get('_field', '—')}</td>
            <td style='{td}color:{pos_c};font-weight:600;text-align:left'>{nm}</td>
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
        </tr>"""
    html += "</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)


def render_spread_table(pairs, theme, top_n=10):
    show = pairs[:top_n]
    pos_c = theme['pos']; neg_c = theme['neg']; short_c = theme['short']
    _bg3 = theme.get('bg3', '#f8fafc')
    _txt2 = theme.get('text2', '#64748b'); _mut = theme.get('muted', '#94a3b8')
    th, td, _bdr = _table_shell(theme)

    html = f"""<div style='overflow-x:auto;border:1px solid {_bdr};border-radius:6px'><table style='border-collapse:collapse;font-family:{FONTS};font-size:11px;width:100%;line-height:1.3'>
        <thead style='background:{_bg3}'><tr>
            <th style='{th}text-align:left'>RANK</th>
            <th style='{th}text-align:right'>FIELD #</th>
            <th style='{th}text-align:left'>LONG</th>
            <th style='{th}text-align:left'>SHORT</th>
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
            <th style='{th}text-align:center'>vs BEST</th>
        </tr></thead><tbody>"""

    for rank, p in enumerate(show, 1):
        ln = SYMBOL_NAMES.get(p['long'], clean_symbol(p['long']))
        sn = SYMBOL_NAMES.get(p['short'], clean_symbol(p['short']))
        sh_c = pos_c if p['Sharpe'] >= 0 else neg_c
        tot_c = pos_c if p['Tot%'] >= 0 else neg_c
        tot_s = '+' if p['Tot%'] >= 0 else ''
        win_c = pos_c if p['Win%'] >= 55 else (neg_c if p['Win%'] < 45 else _txt2)
        er_c = pos_c if p['ER'] >= 0.30 else (_txt2 if p['ER'] >= 0.12 else _mut)
        beats = p.get('beats_outright', False)
        vs = (f"<span style='color:{pos_c};font-weight:700'>▲</span>" if beats
              else f"<span style='color:{_mut}'>—</span>")
        bg = f'linear-gradient(90deg,{pos_c}08,{_bg3},{pos_c}08)' if beats else 'transparent'
        score = p.get('_score', 0)
        sc_c = pos_c if score <= 20 else (_txt2 if score <= 60 else _mut)
        corr = '—' if pd.isna(p['Corr']) else f"{p['Corr']:.2f}"
        html += f"""<tr style='background:{bg}'>
            <td style='{td}color:{_mut};text-align:left'>{rank}</td>
            <td style='{td}color:{_txt2};text-align:right'>{p.get('_field', '—')}</td>
            <td style='{td}color:{pos_c};font-weight:600;text-align:left'>{ln}</td>
            <td style='{td}color:{short_c};font-weight:600;text-align:left'>{sn}</td>
            <td style='{td}text-align:right;color:{sc_c};font-weight:600'>{score:.1f}</td>
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
            <td style='{td}text-align:center'>{vs}</td>
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
                         max_charts=6):
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
        if p['short'] is None:
            subtitles.append(f"<span style='color:{lc}'>■</span> {ln}  (outright)")
        else:
            sn = SYMBOL_NAMES.get(p['short'], clean_symbol(p['short']))
            subtitles.append(
                f"<span style='color:{lc}'>■</span> {ln}  "
                f"<span style='color:{sc}'>■</span> {sn}  "
                f"<span style='color:#0f172a'>■</span> Spread")
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

def render_spreads_tab(is_mobile: bool = False) -> None:
    theme = THEMES.get(st.session_state.get("theme", "Light"), THEMES["Dark"])

    n_inst = len(ALL_SYMBOLS)
    n_pairs_max = n_inst * (n_inst - 1) // 2
    st.caption(
        f"Every instrument as an outright and every long/short pair, ranked in "
        f"**one combined field** — {n_inst} outrights plus {n_pairs_max} pairs. "
        "Both sides are measured identically, so FIELD # answers the only "
        "question that matters: is the spread actually better than just being "
        "long the best thing? Sign is auto-flipped so LONG is the leg to be "
        "long. Calendar periods carry a matched bar size (WTD·1h, MTD·4h, "
        "QTD·daily, YTD·weekly) — override with the Bars selector."
    )

    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 1])
    with c1:
        st.markdown("##### Lookback")
        lb_label = st.selectbox("Lookback", LOOKBACK_OPTIONS, index=1,
                                key="spr_lookback", label_visibility="collapsed")
    with c2:
        st.markdown("##### Bars")
        bar_label = st.selectbox("Bars", list(BAR_OPTIONS), index=0, key="spr_bars",
                                 label_visibility="collapsed")
    with c3:
        st.markdown("##### Fitness")
        sort_by = st.selectbox("Fitness", list(SORT_KEYS), index=0, key="spr_sort",
                               label_visibility="collapsed")
    with c4:
        st.markdown("##### Show")
        show = st.selectbox("Show", ["10", "25", "50", "100", "All"], index=4,
                            key="spr_topn", label_visibility="collapsed")
    with c5:
        st.markdown("##### Charts")
        n_charts = st.selectbox("Charts", [6, 12, 24, 48], index=0,
                                key="spr_charts", label_visibility="collapsed")

    if st.button("Refresh", key="rs"):
        fetch_spread_data.clear()
        st.rerun()

    symbols = ALL_SYMBOLS

    # --- resolve window and bar size ---
    is_period = lb_label in PERIOD_BARS
    if is_period:
        start_dt = period_start(lb_label)
        start_iso = start_dt.isoformat()
        lb_days = 0
        default_interval = PERIOD_BARS[lb_label]
        window_days = max((datetime.now() - start_dt).days, 1)
        window_txt = f"{lb_label} (from {start_dt:%d %b %Y})"
    else:
        start_iso = None
        lb_days = ROLLING_DAYS[lb_label]
        default_interval = auto_interval(lb_days)
        window_days = lb_days
        window_txt = lb_label

    interval = BAR_OPTIONS[bar_label] or default_interval
    pinned = BAR_OPTIONS[bar_label] is not None    # user chose the bar explicitly

    # --- fetch, stepping to a finer bar if the window comes back too thin ---
    n_pairs = len(symbols) * (len(symbols) - 1) // 2
    tried, res, iv = [], None, interval
    while iv is not None:
        cap = _MAX_BACK.get(iv)
        if cap is not None and window_days > cap:
            tried.append((iv, 'beyond Yahoo history limit'))
            iv = _FINER.get(iv)
            continue
        with st.spinner(f"Pricing {len(symbols)} outrights and {n_pairs} pairs "
                        f"on {BAR_NAMES[iv]} bars…"):
            res = fetch_spread_data(tuple(symbols), lb_days, iv, start_iso)
        n_rows = 0 if res['data'] is None else len(res['data'])
        tried.append((iv, f"{n_rows} bars"))
        if n_rows >= MIN_BARS or pinned:
            break
        iv = _FINER.get(iv)
    interval = iv or interval
    bar_name = BAR_NAMES[interval]

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
                    "  — these were shed so the remaining instruments keep their "
                    "full history, rather than every symbol being clipped to the "
                    "sparsest one.")
            if r.get('cov'):
                cdf = pd.DataFrame({
                    'Instrument': [SYMBOL_NAMES.get(s, clean_symbol(s)) for s in r['cov']],
                    'Raw bars': [r['raw'].get(s, 0) for s in r['cov']],
                    'Coverage': [f"{v:.0%}" for v in r['cov'].values()],
                    'Kept': ['—' if s in r.get('dropped', []) else '✓' for s in r['cov']],
                }).sort_values('Coverage')
                st.dataframe(cdf, use_container_width=True, hide_index=True)

    if res is None or res['data'] is None:
        st.warning(
            f"Not enough usable history over {window_txt} on {bar_name} bars. "
            + ("You've pinned the bar size — set Bars back to Auto to let it step "
               "finer automatically. " if pinned else
               "Every finer bar was tried too. ")
            + "Open the panel below to see which instruments came back thin.")
        _diagnostics(res or {'raw': {}, 'cov': {}, 'dropped': []})
        return

    data = res['data']
    if interval != (BAR_OPTIONS[bar_label] or default_interval):
        st.info(f"{BAR_NAMES[default_interval]} bars gave too few observations "
                f"over {window_txt} — stepped down to **{bar_name}**. Pin a bar "
                f"in the Bars selector to override.")

    ann = ann_factor_for(data.index)
    outs = compute_outrights(data, ann)
    pairs = compute_pairs(data, ann)
    if not outs and not pairs:
        st.info("Nothing computed.")
        return

    # --- rank outrights and pairs in ONE field ---
    field = outs + pairs
    rank_field(field)
    key, lower = apply_field_rank(field, sort_by)

    best_out = min(outs, key=lambda c: c['_field']) if outs else None
    if best_out is not None:
        for p in pairs:
            p['beats_outright'] = p['_field'] < best_out['_field']

    outs_sorted = sort_candidates(outs, sort_by)
    pairs_sorted = sort_candidates(pairs, sort_by)

    # --- headline ---
    n_beat = sum(1 for p in pairs if p.get('beats_outright'))
    top_10 = sorted(field, key=lambda c: c['_field'])[:10]
    outs_in_top10 = sum(1 for c in top_10 if c['kind'] == 'outright')
    bo = SYMBOL_NAMES.get(best_out['long'], clean_symbol(best_out['long'])) if best_out else "—"
    bp = pairs_sorted[0] if pairs_sorted else None
    bl = SYMBOL_NAMES.get(bp['long'], clean_symbol(bp['long'])) if bp else "—"
    bs = SYMBOL_NAMES.get(bp['short'], clean_symbol(bp['short'])) if bp else "—"
    metric_txt = sort_by if key != '_score' else "Composite"

    st.markdown(
        f"**{len(outs)} outrights + {len(pairs)} pairs** = {len(field)} candidates  ·  "
        f"{len(data)} {bar_name} bars over {window_txt} (annualised ×{ann:,.0f})  ·  "
        f"ranked by **{metric_txt}**"
    )
    st.markdown(
        f"Best outright: **{bo}** (field #{best_out['_field']}, Sharpe "
        f"{best_out['Sharpe']:.2f}, ER {best_out['ER']:.2f})  ·  "
        f"Best pair: **long {bl} / short {bs}** (field #{bp['_field']}, Sharpe "
        f"{bp['Sharpe']:.2f}, ER {bp['ER']:.2f})  ·  "
        f"**{n_beat} of {len(pairs)} pairs** beat the best outright  ·  "
        f"**{outs_in_top10} of the top 10** are plain outrights"
        if best_out and bp else ""
    )

    # --- sample-size honesty ---
    if len(data) < 100:
        se = (ann / len(data)) ** 0.5
        suggest = ("a finer bar (Bars → 4 Hour or 1 Hour)" if interval in ('1d', '1wk')
                   else "a longer lookback")
        st.warning(
            f"**{len(data)} bars is a thin sample.** Annualised Sharpe carries a "
            f"standard error of roughly ±{se:.1f} here, and {len(field)} candidates "
            f"were tested — the top of the table will look strong from noise alone. "
            f"Try {suggest}. Early in a quarter or year the calendar anchor is "
            f"short by construction: QTD on daily bars in the first month is ~20 "
            f"observations, YTD on weekly is ~1 per week elapsed."
        )

    _diagnostics(res)

    # --- outright leaderboard first ---
    st.markdown(f"##### Outright leaderboard — {len(outs)} instruments by {metric_txt}")
    render_outright_table(outs_sorted, theme, key, top_n=len(outs_sorted))

    st.markdown("")

    # --- then the pairs ---
    top_n = len(pairs_sorted) if show == "All" else int(show)
    st.markdown(f"##### Ranked pairs — {min(top_n, len(pairs_sorted))} of "
                f"{len(pairs_sorted)} by {metric_txt}  ·  ▲ = beats the best outright")
    render_spread_table(pairs_sorted, theme, top_n=top_n)

    st.markdown(f"##### Top {min(n_charts, len(pairs_sorted))} — legs vs spread "
                f"(rebased to 100)")
    render_spread_charts(pairs_sorted, data, theme, mobile=is_mobile,
                         max_charts=n_charts, tick_fmt=_tick_fmt(data.index))
