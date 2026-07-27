"""Sectors tab — spreads inside each sector, where the sessions actually line up.

The all-pairs Spreads tab inner-joins the whole board, so its intraday sample is
capped by the most session-bound instrument on it (grains close, crypto never
does). Running each sector separately lets every group keep its own calendar,
which is usually the difference between 56 usable bars and several hundred.
"""
import pandas as pd
import streamlit as st

from sakata_config import FUTURES_GROUPS, THEMES, SYMBOL_NAMES, clean_symbol
from spreads import (LOOKBACK_OPTIONS, BAR_OPTIONS, SORT_KEYS, _INTRADAY,
                     auto_interval, ann_factor_for, fetch_spread_data,
                     compute_sector_spreads, sort_spread_pairs,
                     render_spread_table, render_spread_charts)

SECTOR_NAMES = [g for g in FUTURES_GROUPS if g != "Macro"]

# sort label -> leaderboard column ("Composite" has no cross-sector meaning
# here, since each sector ranks its pairs against its own field)
_LB_SORT = {"Composite": "Sharpe", "Sharpe": "Sharpe", "Sortino": "Sortino",
            "MAR": "MAR", "R²": "R²", "Total": "Total %", "Win Rate": "Win %"}


def _name(sym):
    return SYMBOL_NAMES.get(sym, clean_symbol(sym))


def _sector_results(sectors, lb_days, interval, sort_by):
    """{sector: (data, sorted_pairs, ann)} — one fetch per sector."""
    out, bar = {}, st.progress(0.0, text="Pricing sectors…")
    for i, sec in enumerate(sectors, 1):
        bar.progress(i / len(sectors), text=f"Pricing {sec}…")
        syms = FUTURES_GROUPS.get(sec, [])
        if len(syms) < 2:
            continue
        try:
            data = fetch_spread_data(tuple(syms), lb_days, interval)
        except Exception:  # noqa: BLE001
            data = None
        if data is None or len(data.columns) < 2:
            continue
        ann = ann_factor_for(data.index)
        pairs = compute_sector_spreads(data, ann)
        if pairs:
            out[sec] = (data, sort_spread_pairs(pairs, sort_by), ann)
    bar.empty()
    return out


def _leaderboard(results) -> pd.DataFrame:
    rows = []
    for sec, (data, pairs, ann) in results.items():
        p = pairs[0]
        rows.append({
            "Sector": sec,
            "Long": _name(p["long"]), "Short": _name(p["short"]),
            "Bars": len(data),
            "Sharpe": p["Sharpe"], "Sortino": p["Sortino"], "MAR": p["MAR"],
            "R²": p["R²"], "Win %": p["Win%"], "Total %": p["Tot%"],
            "Vol %": p["Vol%"], "MDD %": p["MDD%"], "Corr": p["Corr"],
            "Beats": "▲" if p["beats_long"] else "—",
        })
    return pd.DataFrame(rows)


def render_sectors_tab(is_mobile: bool = False) -> None:
    theme = THEMES.get(st.session_state.get("theme", "Light"), THEMES["Dark"])

    st.caption(
        "The same spread engine run inside each sector rather than across the "
        "whole board. Every group keeps its own trading calendar, so the "
        "intraday bar counts hold up and the legs are economically related — "
        "a crush spread rather than corn against nat gas. Check the **Bars** "
        "column: a Sharpe computed on fewer than ~100 observations is noise."
    )

    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    with c1:
        st.markdown("##### Lookback")
        lb_label = st.selectbox("Lookback", list(LOOKBACK_OPTIONS), index=3,
                                key="sec_lookback", label_visibility="collapsed")
    with c2:
        st.markdown("##### Bars")
        bar_label = st.selectbox("Bars", list(BAR_OPTIONS), index=0,
                                 key="sec_bars", label_visibility="collapsed")
    with c3:
        st.markdown("##### Sort by")
        sort_by = st.selectbox("Sort", list(SORT_KEYS), index=0, key="sec_sort",
                               label_visibility="collapsed")
    with c4:
        st.markdown("##### Charts")
        n_charts = st.selectbox("Charts", [0, 2, 3, 6], index=2, key="sec_charts",
                                label_visibility="collapsed")

    sectors = st.multiselect("Sectors", list(FUTURES_GROUPS), default=SECTOR_NAMES,
                             key="sec_pick")
    if st.button("Refresh", key="rsec"):
        fetch_spread_data.clear()
        st.rerun()
    if not sectors:
        st.info("Pick at least one sector.")
        return

    lb_days = LOOKBACK_OPTIONS[lb_label]
    interval = BAR_OPTIONS[bar_label] or auto_interval(lb_days)
    bar_name = {"4h": "4-hour", "1h": "hourly", "1d": "daily"}[interval]
    tick_fmt = "%d %b %H:%M" if interval in _INTRADAY else "%d %b"

    results = _sector_results(sectors, lb_days, interval, sort_by)
    if not results:
        st.warning(f"No sector returned usable history over {lb_label} on "
                   f"{bar_name} bars. Try a longer lookback or daily bars.")
        return

    # ---------------- leaderboard: best pair in each sector ----------------
    st.markdown(f"##### Best pair per sector — {bar_name} bars, {lb_label}, "
                f"ranked by {sort_by}")

    def sign_colour(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "color:#9ca3af;"
        return ("color:#16a34a;font-weight:600;" if v >= 0
                else "color:#dc2626;font-weight:600;")

    def thin_bars(v):
        return "color:#dc2626;font-weight:600;" if v < 100 else "color:#334155;"

    lb = _leaderboard(results).sort_values(_LB_SORT.get(sort_by, "Sharpe"),
                                           ascending=False, ignore_index=True)
    st.table(
        lb.style
        .map(sign_colour, subset=["Sharpe", "Sortino", "Total %", "R²"])
        .map(thin_bars, subset=["Bars"])
        .format({"Sharpe": "{:.2f}", "Sortino": "{:.2f}", "MAR": "{:.1f}",
                 "R²": "{:.3f}", "Win %": "{:.0f}%", "Total %": "{:+.1f}%",
                 "Vol %": "{:.1f}%", "MDD %": "{:.1f}%", "Corr": "{:.2f}"})
        .hide(axis="index")
    )
    thin = [s for s, (d, _p, _a) in results.items() if len(d) < 100]
    if thin:
        st.caption(f"⚠ Thin sample on {', '.join(thin)} — fewer than 100 bars. "
                   f"Treat those Sharpes as unranked.")

    st.divider()

    # ---------------- per-sector detail ----------------
    for sec in [s for s in sectors if s in results]:
        data, pairs, ann = results[sec]
        p = pairs[0]
        st.markdown(f"##### {sec}")
        st.markdown(
            f"{len(pairs)} pair{'s' if len(pairs) > 1 else ''} from "
            f"{len(data.columns)} instruments  ·  {len(data)} {bar_name} bars "
            f"(annualised ×{ann:,.0f})  ·  top: **long {_name(p['long'])} / "
            f"short {_name(p['short'])}** at Sharpe **{p['Sharpe']:.2f}**"
        )
        render_spread_table(pairs, theme, top_n=10)
        if n_charts:
            render_spread_charts(pairs, data, theme, mobile=is_mobile,
                                 tick_fmt=tick_fmt, max_charts=n_charts)
        st.divider()
