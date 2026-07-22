"""Board tab — sector performance scanner."""
import altair as alt
import pandas as pd
import streamlit as st

from common import SECTORS, get_perf


def build_scanner() -> pd.DataFrame:
    rows = []
    for sector, members in SECTORS.items():
        for name, (ticker, dec) in members.items():
            p = get_perf(ticker)
            last = p.get("last")
            rows.append({
                "Instrument": name.strip(), "Sector": sector,
                "Last": f"{last:,.{dec}f}" if last else "—",
                "Day %": p.get("day", float("nan")),
                "WTD %": p.get("wtd", float("nan")),
                "MTD %": p.get("mtd", float("nan")),
                "QTD %": p.get("qtd", float("nan")),
                "YTD %": p.get("ytd", float("nan")),
            })
    return pd.DataFrame(rows)


def render_board() -> None:
    df = build_scanner()
    horizons = ["Day %", "WTD %", "MTD %", "QTD %", "YTD %"]

    def pct_colour(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "color:#9ca3af;"
        return "color:#16a34a;font-weight:600;" if v >= 0 else "color:#dc2626;font-weight:600;"

    def fmt_pct(v):
        return "—" if v is None or pd.isna(v) else f"{v:+.2f}%"

    fmt_map = {h: fmt_pct for h in horizons}

    # controls row
    c1, c2 = st.columns([4, 1])
    with c1:
        hz = st.radio("Horizon", horizons, index=0, horizontal=True,
                      label_visibility="collapsed")
    with c2:
        if st.button("Refresh", key="rb"):
            st.cache_data.clear()
            st.rerun()

    # --- sector performance: horizontal bar chart ---
    st.markdown(f"##### Sector performance · {hz}")
    agg = (df.groupby("Sector", sort=False)[horizons].mean().reset_index())
    agg["_v"] = agg[hz]
    agg = agg.sort_values("_v", ascending=False)
    bar = (alt.Chart(agg).mark_bar(cornerRadius=2, height=16).encode(
        x=alt.X("_v:Q", title=None, axis=alt.Axis(format="+.1f", grid=True,
                gridColor="#f1f5f9")),
        y=alt.Y("Sector:N", sort=list(agg["Sector"]), title=None,
                axis=alt.Axis(labelFontSize=12, labelColor="#334155")),
        color=alt.condition("datum._v >= 0", alt.value("#16a34a"), alt.value("#dc2626")),
        tooltip=[alt.Tooltip("Sector:N"), alt.Tooltip("_v:Q", format="+.2f", title=hz)],
    ).properties(height=28 * len(agg) + 10).configure_view(strokeWidth=0)
        .configure_axis(labelColor="#64748b"))
    st.altair_chart(bar, use_container_width=True)

    # --- full scanner (tight table, all rows in one shot) ---
    st.markdown("##### Scanner")
    st.table(
        df.style.map(pct_colour, subset=horizons).format(fmt_map).hide(axis="index")
    )
