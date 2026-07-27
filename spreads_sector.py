"""Spreads · Sector — every pair inside one group, ranked."""
import streamlit as st

from sanpo_config import FUTURES_GROUPS, THEMES, SYMBOL_NAMES, clean_symbol
from spreads import (LOOKBACK_OPTIONS, SORT_KEYS, fetch_sector_spread_data,
                     compute_sector_spreads, sort_spread_pairs,
                     render_spread_table, render_spread_charts)


def render_sector_tab(is_mobile: bool = False) -> None:
    theme = THEMES.get(st.session_state.get("theme", "Light"), THEMES["Dark"])

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        st.markdown("##### Group")
        group = st.selectbox("Group", list(FUTURES_GROUPS), index=0,
                             key="spr_group", label_visibility="collapsed")
    with c2:
        st.markdown("##### Lookback")
        lb_label = st.selectbox("Lookback", list(LOOKBACK_OPTIONS), index=0,
                                key="spr_lookback", label_visibility="collapsed")
    with c3:
        st.markdown("##### Sort by")
        sort_by = st.selectbox("Sort", list(SORT_KEYS), index=0,
                               key="spr_sort", label_visibility="collapsed")

    if st.button("Refresh", key="rs_sector"):
        fetch_sector_spread_data.clear()
        st.rerun()

    with st.spinner(f"Pricing {group} pairs…"):
        data = fetch_sector_spread_data(group, LOOKBACK_OPTIONS[lb_label])

    if data is None or len(data.columns) < 2:
        st.warning(f"Not enough price history for {group} over {lb_label}.")
        return

    pairs = compute_sector_spreads(data)
    if not pairs:
        st.info("No pairs computed.")
        return

    pairs = sort_spread_pairs(pairs, sort_by)
    best = pairs[0]
    bl = SYMBOL_NAMES.get(best["long"], clean_symbol(best["long"]))
    bs = SYMBOL_NAMES.get(best["short"], clean_symbol(best["short"]))
    outright = SYMBOL_NAMES.get(best["best_long_sym"],
                                clean_symbol(best["best_long_sym"]))
    st.markdown(
        f"**{group}**  ·  {len(pairs)} pairs over {lb_label}  ·  "
        f"top by {sort_by}: **long {bl} / short {bs}**  ·  "
        f"Sharpe **{best['Sharpe']:.2f}** vs best outright "
        f"{outright} {best['best_long_sharpe']:.2f}"
    )

    st.markdown("##### Ranked pairs")
    render_spread_table(pairs, theme, top_n=12)

    st.markdown("##### Top 6 — legs vs spread (rebased to 100)")
    render_spread_charts(pairs, data, theme, mobile=is_mobile)
