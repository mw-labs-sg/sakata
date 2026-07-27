import streamlit as st
import yfinance as yf

from common import _session
import pandas as pd
import numpy as np
from datetime import datetime
from itertools import combinations
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging

from sakata_config import ALL_SYMBOLS, THEMES, SYMBOL_NAMES, FONTS, clean_symbol

logger = logging.getLogger(__name__)

# =============================================================================
# SPREAD STATISTICS
# =============================================================================

def _spread_sharpe(returns, ann_factor=252):
    if returns.std() == 0 or len(returns) < 5: return 0.0
    return float((returns.mean() / returns.std()) * np.sqrt(ann_factor))

def _spread_sortino(returns, ann_factor=252):
    if returns.std() == 0 or len(returns) < 5: return 0.0
    ann_ret = returns.mean() * ann_factor
    down = returns[returns < 0]
    down_std = np.sqrt(np.mean(down**2)) * np.sqrt(ann_factor) if len(down) > 0 else 0
    return float(ann_ret / down_std) if down_std else 0.0

def _spread_drawdowns(returns):
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = float(dd.min() * 100)
    add = float(dd[dd < 0].mean() * 100) if (dd < 0).any() else 0.0
    return mdd, add

def _spread_r2(returns):
    if len(returns) < 5: return 0.0
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

# =============================================================================
# DATA FETCHING
# =============================================================================

LOOKBACK_OPTIONS = {
    '1 Day': 1, '5 Days': 5, '10 Days': 10, '20 Days': 20, '30 Days': 30,
    '60 Days': 60, '120 Days': 120, '240 Days': 240, '520 Days': 520, 'YTD': 0,
}

# Yahoo intraday limits: 15m/30m reach back ~60 days, 1h ~730 days. There is no
# native 4h bar — it is resampled from 1h.
BAR_OPTIONS = {'Auto': None, '15 Min': '15m', '30 Min': '30m', '1 Hour': '1h',
               '4 Hour': '4h', 'Daily': '1d'}
_INTRADAY = ('15m', '30m', '1h', '4h')
_NATIVE = {'15m': '15m', '30m': '30m', '1h': '1h', '4h': '1h', '1d': '1d'}
_MAX_BACK = {'15m': 55, '30m': 55, '1h': 700, '4h': 700, '1d': None}

# lookback (days) -> bar size, coarsening as the window widens so every window
# lands in the low hundreds of observations rather than tens.
_LADDER = ((2, '15m'), (7, '30m'), (20, '1h'), (60, '4h'))


def auto_interval(lookback_days):
    """Short windows get finer bars — 30 daily closes is not a sample."""
    if lookback_days == 0:
        return '1d'
    for limit, interval in _LADDER:
        if lookback_days <= limit:
            return interval
    return '1d'


def ann_factor_for(index):
    """Bars per year, measured off the data rather than assumed.

    Self-calibrating: a year of daily closes gives ~252, a 30-day window of 4h
    bars gives ~1500. Keeps Sharpe/Sortino/vol comparable across bar types.
    """
    if len(index) < 3:
        return 252.0
    span_yrs = (index[-1] - index[0]).total_seconds() / (365.25 * 24 * 3600)
    if span_yrs <= 0:
        return 252.0
    return float(np.clip(len(index) / span_yrs, 12, 8760))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_spread_data(symbols_tuple, lookback_days=0, interval='1d'):
    """Rebased (=100) close matrix for an arbitrary set of tickers.

    Daily bars are forward-filled then aligned. Intraday bars are NOT
    forward-filled — a stale grain price carried through a closed session
    would show as a zero return and flatter the vol and Sharpe. Instead the
    columns are inner-joined, so every row is a genuinely simultaneous
    observation across all legs.
    """
    symbols = list(symbols_tuple)
    if len(symbols) < 2:
        return None
    intraday = interval in _INTRADAY
    yf_interval = _NATIVE[interval]

    if lookback_days == 0:
        start = datetime.now().replace(month=1, day=1)
    else:
        pad = 3 if lookback_days <= 5 else 1.5   # short windows need weekend slack
        start = datetime.now() - pd.Timedelta(days=int(lookback_days * pad) + 2)
    cap = _MAX_BACK.get(interval)
    if cap:   # respect Yahoo's per-interval history limit
        start = max(start, datetime.now() - pd.Timedelta(days=cap))

    data = pd.DataFrame()
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym, session=_session)
            hist = ticker.history(start=start.strftime('%Y-%m-%d'),
                                  interval=yf_interval)
            if hist.empty:
                continue
            closes = hist['Close'].copy()
            closes.index = closes.index.tz_localize(None) if closes.index.tz else closes.index
            if intraday:
                if interval == '4h':
                    closes = closes.resample('4h').last().dropna()
            else:
                closes.index = closes.index.normalize()
            closes = closes.groupby(closes.index).last()
            data[sym] = closes
        except Exception as e:
            logger.debug(f"[{sym}] spread data fetch error: {e}")

    if data.empty or len(data.columns) < 2:
        return None
    data = data.dropna() if intraday else data.ffill().dropna()
    if lookback_days > 0 and not data.empty:
        cutoff = data.index.max() - pd.Timedelta(days=lookback_days)
        data = data[data.index >= cutoff]
    if len(data) < 10:
        return None
    return 100 * (data / data.iloc[0])


# =============================================================================
# SPREAD COMPUTATION
# =============================================================================

def compute_sector_spreads(data, ann_factor=252):
    if data is None or len(data.columns) < 2: return []

    asset_sharpes = {}
    for sym in data.columns:
        ret = data[sym].pct_change().dropna()
        asset_sharpes[sym] = _spread_sharpe(ret, ann_factor)
    best_long_sym = max(asset_sharpes, key=asset_sharpes.get)
    best_long_sharpe = asset_sharpes[best_long_sym]

    pairs = []
    for s1, s2 in combinations(data.columns.tolist(), 2):
        r1 = data[s1].pct_change().dropna()
        r2 = data[s2].pct_change().dropna()
        spread_ret = (r1 - r2).dropna()

        sh = _spread_sharpe(spread_ret, ann_factor)
        so = _spread_sortino(spread_ret, ann_factor)

        if sh < 0:
            spread_ret = -spread_ret
            sh, so = -sh, -so
            s1, s2 = s2, s1

        mdd, add = _spread_drawdowns(spread_ret)
        cum_spread = (1 + spread_ret).cumprod()
        total = float((cum_spread.iloc[-1] - 1) * 100)
        ann = float(spread_ret.mean() * ann_factor * 100)
        vol = float(spread_ret.std() * np.sqrt(ann_factor) * 100)
        mar = float(ann / abs(add)) if add != 0 else 0.0
        r2_val = _spread_r2(spread_ret)
        corr = float(r1.corr(r2))
        win_rate = float((spread_ret > 0).sum() / len(spread_ret) * 100) if len(spread_ret) > 0 else 50.0

        cum1 = data[s1]
        cum2 = data[s2]
        cum_sp = pd.Series(100.0, index=data.index[:1])
        cum_sp = pd.concat([cum_sp, 100 * (1 + spread_ret).cumprod()])
        cum_sp = cum_sp[~cum_sp.index.duplicated(keep='last')]

        pairs.append({
            'long': s1, 'short': s2,
            'Sharpe': sh, 'Sortino': so, 'MAR': mar, 'R²': r2_val,
            'Tot%': total, 'Ann%': ann, 'Vol%': vol, 'MDD%': mdd, 'ADD%': add,
            'Corr': corr, 'Win%': win_rate, 'beats_long': sh > best_long_sharpe,
            'cum_long': cum1, 'cum_short': cum2, 'cum_spread': cum_sp,
        })

    n = len(pairs)
    if n == 0: return []
    for metric in ['Sharpe', 'Sortino', 'MAR', 'R²']:
        vals = [p[metric] for p in pairs]
        order = sorted(range(n), key=lambda i: -vals[i])
        for rank, idx in enumerate(order): pairs[idx][f'_{metric}_rank'] = rank + 1
    for p in pairs:
        p['_score'] = np.mean([p[f'_{m}_rank'] for m in ['Sharpe', 'Sortino', 'MAR', 'R²']])
    pairs.sort(key=lambda x: -x['Sharpe'])

    for p in pairs:
        p['best_long_sym'] = best_long_sym
        p['best_long_sharpe'] = best_long_sharpe

    return pairs

# =============================================================================
# SORTING
# =============================================================================

SORT_KEYS = {
    'Composite': '_score', 'Sharpe': 'Sharpe', 'Sortino': 'Sortino',
    'MAR': 'MAR', 'R²': 'R²', 'Total': 'Tot%', 'Win Rate': 'Win%'
}

def sort_spread_pairs(pairs, sort_key='Composite', ascending=False):
    key = SORT_KEYS.get(sort_key, sort_key)
    default_reverse = (key != '_score')
    reverse = not default_reverse if ascending else default_reverse
    return sorted(pairs, key=lambda x: x.get(key, 0), reverse=reverse)

# =============================================================================
# SHARED TABLE RENDERER
# =============================================================================

def render_spread_table(pairs, theme, top_n=10):
    show = pairs[:top_n]
    pos_c = theme['pos']; neg_c = theme['neg']; short_c = theme['short']
    _bg3 = theme.get('bg3', '#f8fafc'); _bdr = theme.get('border', '#e2e8f0')
    _txt = theme.get('text', '#334155'); _txt2 = theme.get('text2', '#64748b'); _mut = theme.get('muted', '#94a3b8')
    th = f"padding:4px 8px;border-bottom:1px solid {_bdr};color:#475569;font-weight:600;font-size:9px;text-transform:uppercase;letter-spacing:0.06em;"
    td = f"padding:5px 8px;border-bottom:1px solid {_bdr}22;"

    html = f"""<div style='overflow-x:auto;border:1px solid {_bdr};border-radius:6px'><table style='border-collapse:collapse;font-family:{FONTS};font-size:11px;width:100%;line-height:1.3'>
        <thead style='background:{_bg3}'><tr>
            <th style='{th}text-align:left'>RANK</th>
            <th style='{th}text-align:left'>LONG</th>
            <th style='{th}text-align:left'>SHORT</th>
            <th style='{th}text-align:right'>SCORE</th>
            <th style='{th}text-align:right'>SHARPE</th>
            <th style='{th}text-align:right'>SORTINO</th>
            <th style='{th}text-align:right'>MAR</th>
            <th style='{th}text-align:right'>R²</th>
            <th style='{th}text-align:right'>WIN%</th>
            <th style='{th}text-align:right'>TOT%</th>
            <th style='{th}text-align:right'>VOL%</th>
            <th style='{th}text-align:right'>MDD%</th>
            <th style='{th}text-align:right'>CORR</th>
            <th style='{th}text-align:center'>vs LONG</th>
        </tr></thead><tbody>"""

    for rank, p in enumerate(show, 1):
        ln = SYMBOL_NAMES.get(p['long'], clean_symbol(p['long']))
        sn = SYMBOL_NAMES.get(p['short'], clean_symbol(p['short']))
        sh_c = pos_c if p['Sharpe'] >= 0 else neg_c
        tot_c = pos_c if p['Tot%'] >= 0 else neg_c
        tot_s = '+' if p['Tot%'] >= 0 else ''
        win_c = pos_c if p['Win%'] >= 55 else (neg_c if p['Win%'] < 45 else _txt2)
        vs = f"<span style='color:{pos_c};font-weight:700'>▲</span>" if p['beats_long'] else f"<span style='color:{_mut}'>—</span>"
        bg = f'linear-gradient(90deg,{pos_c}08,{_bg3},{pos_c}08)' if p['beats_long'] else 'transparent'
        score = p.get('_score', 0)
        sc_c = pos_c if score <= 3 else (_txt2 if score <= 6 else _mut)
        html += f"""<tr style='background:{bg}'>
            <td style='{td}color:{_mut};text-align:left'>{rank}</td>
            <td style='{td}color:{pos_c};font-weight:600;text-align:left'>{ln}</td>
            <td style='{td}color:{short_c};font-weight:600;text-align:left'>{sn}</td>
            <td style='{td}text-align:right;color:{sc_c};font-weight:600'>{score:.1f}</td>
            <td style='{td}text-align:right'><span style='color:{sh_c};font-weight:700'>{p["Sharpe"]:.2f}</span></td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["Sortino"]:.2f}</td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["MAR"]:.2f}</td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["R²"]:.3f}</td>
            <td style='{td}text-align:right'><span style='color:{win_c};font-weight:600'>{p["Win%"]:.0f}%</span></td>
            <td style='{td}text-align:right'><span style='color:{tot_c};font-weight:600'>{tot_s}{p["Tot%"]:.1f}%</span></td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["Vol%"]:.1f}%</td>
            <td style='{td}text-align:right;color:{neg_c}'>{p["MDD%"]:.1f}%</td>
            <td style='{td}text-align:right;color:{_txt2}'>{p["Corr"]:.2f}</td>
            <td style='{td}text-align:center'>{vs}</td>
        </tr>"""
    html += "</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)

# =============================================================================
# SHARED CHART RENDERER
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
    if top_n == 0: return

    _pbg = theme.get('plot_bg', '#ffffff'); _grd = theme.get('grid', '#eef2f6')
    _axl = theme.get('axis_line', '#e2e8f0'); _tk = theme.get('tick', '#94a3b8')
    _mut = theme.get('muted', '#94a3b8')

    n_cols = 1 if mobile else min(3, top_n)
    n_rows = (top_n + n_cols - 1) // n_cols

    subtitles = []
    for i in range(top_n):
        ln = SYMBOL_NAMES.get(pairs[i]['long'], clean_symbol(pairs[i]['long']))
        sn = SYMBOL_NAMES.get(pairs[i]['short'], clean_symbol(pairs[i]['short']))
        lc = theme['long']; sc = theme['short']
        subtitles.append(f"<span style='color:{lc}'>■</span> {ln}  <span style='color:{sc}'>■</span> {sn}  <span style='color:#0f172a'>■</span> Spread")
    while len(subtitles) < n_rows * n_cols: subtitles.append("")

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
        fig.add_trace(go.Scatter(x=list(range(len(p['cum_long']))), y=p['cum_long'].values,
            mode='lines', line=dict(color=theme['long'], width=1.3, shape='spline', smoothing=1.0),
            showlegend=False, hovertemplate='Long: %{y:.1f}<extra></extra>'), row=row, col=col)
        fig.add_trace(go.Scatter(x=list(range(len(p['cum_short']))), y=p['cum_short'].values,
            mode='lines', line=dict(color=theme['short'], width=1.3, shape='spline', smoothing=1.0),
            showlegend=False, hovertemplate='Short: %{y:.1f}<extra></extra>'), row=row, col=col)
        fig.add_trace(go.Scatter(x=list(range(len(p['cum_spread']))), y=p['cum_spread'].values,
            mode='lines', line=dict(color='#0f172a', width=1.5, dash='dot', shape='spline', smoothing=1.0),
            showlegend=False, hovertemplate='Spread: %{y:.1f}<extra></extra>'), row=row, col=col)
        fig.add_hline(y=100, line=dict(color=_grd, width=0.8, dash='dot'), row=row, col=col)

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
        fig.update_layout(**{axis_key: dict(tickmode='array', tickvals=tick_vals, ticktext=tick_text)})

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
        tickfont=dict(color=_tk, size=8, family=FONTS), showgrid=False, tickangle=0)
    fig.update_yaxes(gridcolor=_grd, linecolor=_axl,
        tickfont=dict(color=_tk, size=8, family=FONTS), side='right')

    st.plotly_chart(fig, use_container_width=True, config={
        'scrollZoom': True, 'displayModeBar': False, 'responsive': True})

# =============================================================================
# MAIN RENDER — one scan across the whole board
# =============================================================================

def render_spreads_tab(is_mobile: bool = False) -> None:
    theme = THEMES.get(st.session_state.get("theme", "Light"), THEMES["Dark"])

    st.caption(
        "Every long/short pair on the board, ranked — 171 combinations across "
        "19 instruments. Each leg is rebased to 100 and the spread is the "
        "return difference. Sign is auto-flipped so Sharpe reads positive, so "
        "the LONG column is the leg to be long; **vs LONG** marks pairs that "
        "beat the best single outright. On Auto the bar size follows the "
        "window: 15m under 2 days, 30m to a week, hourly to 20 days, 4-hour to "
        "60, daily beyond. Intraday rows are inner-joined rather than "
        "forward-filled, so mixing 24h and session-bound markets keeps only "
        "the overlapping bars — watch the bar count in the summary line."
    )

    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 1])
    with c1:
        st.markdown("##### Lookback")
        lb_label = st.selectbox("Lookback", list(LOOKBACK_OPTIONS), index=4,
                                key="spr_lookback", label_visibility="collapsed")
    with c2:
        st.markdown("##### Bars")
        bar_label = st.selectbox("Bars", list(BAR_OPTIONS), index=0, key="spr_bars",
                                 label_visibility="collapsed")
    with c3:
        st.markdown("##### Sort by")
        sort_by = st.selectbox("Sort", list(SORT_KEYS), index=0, key="spr_sort",
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

    lb_days = LOOKBACK_OPTIONS[lb_label]
    interval = BAR_OPTIONS[bar_label] or auto_interval(lb_days)
    bar_name = {'15m': '15-minute', '30m': '30-minute', '1h': 'hourly',
                '4h': '4-hour', '1d': 'daily'}[interval]

    n_pairs = len(symbols) * (len(symbols) - 1) // 2
    with st.spinner(f"Pricing {n_pairs} pairs across {len(symbols)} instruments "
                    f"on {bar_name} bars…"):
        data = fetch_spread_data(tuple(symbols), lb_days, interval)

    if data is None or len(data.columns) < 2:
        st.warning(f"Not enough price history over {lb_label}. "
                   "Yahoo may be throttling — try Refresh in a minute.")
        return

    ann = ann_factor_for(data.index)
    pairs = compute_sector_spreads(data, ann)
    if not pairs:
        st.info("No pairs computed.")
        return

    pairs = sort_spread_pairs(pairs, sort_by)
    best = pairs[0]
    bl = SYMBOL_NAMES.get(best["long"], clean_symbol(best["long"]))
    bs = SYMBOL_NAMES.get(best["short"], clean_symbol(best["short"]))
    outright = SYMBOL_NAMES.get(best["best_long_sym"],
                                clean_symbol(best["best_long_sym"]))
    n_beat = sum(1 for p in pairs if p["beats_long"])
    st.markdown(
        f"**{len(pairs)} pairs** from {len(data.columns)} instruments  ·  "
        f"{len(data)} {bar_name} bars over {lb_label} (annualised ×{ann:,.0f})  ·  "
        f"top by {sort_by}: "
        f"**long {bl} / short {bs}** at Sharpe **{best['Sharpe']:.2f}**  ·  "
        f"{n_beat} beat the best outright ({outright} {best['best_long_sharpe']:.2f})"
    )

    if len(data) < 100:
        st.warning(
            f"**{len(data)} bars is a thin sample.** Annualised Sharpe carries a "
            f"standard error of roughly {(ann / len(data)) ** 0.5:.1f} here, and "
            f"{len(pairs)} pairs were tested — the top of the table will look "
            f"strong from noise alone. Widen the lookback or use finer bars."
        )

    top_n = len(pairs) if show == "All" else int(show)
    st.markdown(f"##### Ranked pairs — {min(top_n, len(pairs))} of {len(pairs)} "
                f"by {sort_by}")
    render_spread_table(pairs, theme, top_n=top_n)

    st.markdown(f"##### Top {min(n_charts, len(pairs))} — legs vs spread "
                f"(rebased to 100)")
    render_spread_charts(pairs, data, theme, mobile=is_mobile, max_charts=n_charts,
                         tick_fmt=_tick_fmt(data.index))
