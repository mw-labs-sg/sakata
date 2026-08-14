"""Sakata on Streamlit.

Two layers of cache, both 15 minutes: prices, and the computed spread field.
The field is the expensive one — nine windows, ~190 candidates each — so it is
computed once and every window switch reads from the same object.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import sk_board as BOARD
import sk_sources as S
import sk_spreads as SP
import sk_universe as U

st.set_page_config(page_title="Sakata", layout="wide")
S.DRY = False
TTL = 900          # 15 minutes, matching the shortest bar


@st.cache_data(ttl=TTL, show_spinner="fetching prices…")
def prices(interval: str, period: str) -> dict:
    return S.fetch_ohlc(interval, period)


@st.cache_data(ttl=TTL, show_spinner="ranking the field…")
def spread_field() -> dict:
    """Every window, sliced from four bar sizes. Mirrors build.py exactly."""
    m15 = prices("15m", "60d")
    hourly = prices("1h", "730d")
    daily = prices("1d", "10y")
    four_h = {k: S.resample_4h(v) for k, v in hourly.items()}

    def closes(frames):
        return {U.TICKER[c]: df["close"].dropna()
                for c, df in frames.items() if df is not None and len(df)}

    return SP.build_spreads({"15m": closes(m15), "1h": closes(hourly),
                             "4h": closes(four_h), "1d": closes(daily)})


st.title("Sakata")
if st.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

tab_board, tab_spreads = st.tabs(["Board", "Spreads"])

# ------------------------------------------------------------------ board
with tab_board:
    daily = prices("1d", "10y")
    if not daily:
        st.error("No daily data — Yahoo returned nothing.")
        st.stop()
    df = pd.DataFrame(BOARD.build_board(daily)["rows"])
    pct = ("Day", "WTD", "MTD", "QTD", "YTD")
    for group in U.GROUPS:
        sub = df[df["group"] == group]
        if sub.empty:
            continue
        st.subheader(group)
        st.dataframe(
            sub[["code", "name", "sector", "last", *pct]],
            hide_index=True, use_container_width=True,
            column_config={c: st.column_config.NumberColumn(c, format="%.2f%%")
                           for c in pct})

# ---------------------------------------------------------------- spreads
with tab_spreads:
    field = spread_field()
    if not field.get("periods"):
        st.error("No spread windows built — not enough price history.")
        st.stop()

    window = st.radio("Window", field["periods"], horizontal=True,
                      label_visibility="collapsed")
    w = field["data"][window]

    st.caption(w["note"])
    c = st.columns(5)
    c[0].metric("Bars", w["bars"])
    c[1].metric("Instruments", w["instruments"])
    c[2].metric("Sharpe SE", f"±{w['se']}")
    c[3].metric("Field", w["nField"])
    c[4].metric("Best outright rank", w["outRank"] or "—")

    if w["dropped"]:
        st.caption("Dropped for coverage: " + ", ".join(w["dropped"]))

    # ------------------------------------------------------------- table
    rows = pd.DataFrame(w["rows"])
    rows["position"] = [
        (f"{r.long}/{r.short}" if r.long and r.short
         else f"long {r.long}" if r.long else f"short {r.short}")
        for r in rows.itertuples()]
    st.dataframe(
        rows[["n", "position", "kind", "sector", "score", "sharpe", "er",
              "win", "tot", "vol", "mdd", "corr", "ratio"]],
        hide_index=True, use_container_width=True, height=420)

    # ------------------------------------------------------------ charts
    st.subheader("Why these ranked")
    for ch in w["charts"]:
        fig = go.Figure()
        if ch["lg"]:
            fig.add_scatter(x=ch["t"], y=ch["lg"], name=f"long {ch['lgName']}",
                            line=dict(width=1, color="#94a3b8"))
        if ch["sh"]:
            fig.add_scatter(x=ch["t"], y=ch["sh"], name=f"short {ch['shName']}",
                            line=dict(width=1, color="#cbd5e1"))
        fig.add_scatter(x=ch["t"], y=ch["sp"], name="spread",
                        line=dict(width=2.5, color="#d97706"))
        fig.update_layout(
            title=(f"{ch['n']}. {ch['label']} — Sharpe {ch['sharpe']}, "
                   f"ER {ch['er']}, total {ch['tot']}%"),
            height=280, margin=dict(l=0, r=0, t=40, b=0),
            legend=dict(orientation="h", y=1.02, yanchor="bottom"),
            xaxis=dict(showgrid=False), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

    # -------------------------------------------------------- persistence
    if field.get("persist"):
        st.subheader("Holds across windows")
        st.caption("Nine windows agreeing is the only evidence here that a "
                   "relationship is structural rather than a fortnight of luck.")
        st.dataframe(pd.DataFrame(field["persist"])[
            ["label", "kind", "count", "best", "avgRank", "medSharpe", "medER"]],
            hide_index=True, use_container_width=True)
