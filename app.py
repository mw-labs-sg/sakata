"""Sakata on Streamlit.

Two layers of cache, both 15 minutes: prices, and the computed spread field.
The field is the expensive one — nine windows, ~190 candidates each — so it is
computed once and every window switch reads from the same object.
"""
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import sk_board as BOARD
import sk_sources as S
import sk_spreads as SP
import sk_theme as TH
import sk_universe as U

st.set_page_config(page_title="Sakata · futures terminal", layout="wide")
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


TH.apply(stamp=dt.datetime.utcnow().strftime("%d %b %H:%M UTC"))
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

    def pct_style(v):
        if pd.isna(v):
            return ""
        return f"color:{TH.T['pos'] if v > 0 else TH.T['neg']}"

    for group in U.GROUPS:
        sub = df[df["group"] == group]
        if sub.empty:
            continue
        st.markdown(f'<div class="sk-ctitle">{group}</div>',
                    unsafe_allow_html=True)
        view = sub[["code", "name", "sector", "last", *pct]].copy()
        st.dataframe(
            view.style.map(pct_style, subset=list(pct))
                .format({c: "{:+.2f}%" for c in pct}, na_rep="—"),
            hide_index=True, use_container_width=True,
            row_height=30)

# ---------------------------------------------------------------- spreads
with tab_spreads:
    field = spread_field()
    if not field.get("periods"):
        st.error("No spread windows built — not enough price history.")
        st.stop()

    window = st.radio("Window", field["periods"], horizontal=True,
                      label_visibility="collapsed")
    w = field["data"][window]

    TH.caption(f"{w['note']} · {w['start']} to {w['end']}")

    c = st.columns(5)
    c[0].metric("Bars", w["bars"])
    c[1].metric("Instruments", w["instruments"])
    c[2].metric("Sharpe SE", f"±{w['se']}")
    c[3].metric("Field", w["nField"])
    c[4].metric("Best outright", f"#{w['outRank']}" if w["outRank"] else "—")

    # The noise band is the point of shipping SE. A Sharpe inside it is not a
    # finding, however high it reads.
    if w["noise"]:
        TH.caption(f"Anything under a Sharpe of {w['noise']} is inside the "
                   f"noise band for a window this short.")
    if w["dropped"]:
        TH.caption("Dropped for coverage: " + ", ".join(w["dropped"]))

    # ------------------------------------------------------------- table
    rows = pd.DataFrame(w["rows"])
    rows["position"] = [
        (f"{r.long}/{r.short}" if r.long and r.short
         else f"long {r.long}" if r.long else f"short {r.short}")
        for r in rows.itertuples()]
    cols = ["n", "position", "kind", "sector", "score", "sharpe", "er",
            "win", "tot", "vol", "mdd", "corr", "ratio"]
    st.dataframe(
        rows[cols].style
            .map(lambda v: f"color:{TH.T['pos'] if v and v > 0 else TH.T['neg']}",
                 subset=["tot"])
            .format({"score": "{:.1f}", "sharpe": "{:.2f}", "er": "{:.3f}",
                     "win": "{:.0f}", "tot": "{:+.1f}", "vol": "{:.1f}",
                     "mdd": "{:.1f}", "corr": "{:.2f}", "ratio": "{:.2f}"},
                    na_rep="—"),
        hide_index=True, use_container_width=True, height=430, row_height=30)

    # ------------------------------------------------------------ charts
    st.markdown("")
    for ch in w["charts"]:
        TH.ctitle(f"{ch['n']}. {ch['label']}",
                  f"Sharpe {ch['sharpe']} · ER {ch['er']} · {ch['tot']:+}%")
        fig = go.Figure()
        if ch["lg"]:
            fig.add_scatter(x=ch["t"], y=ch["lg"], name=ch["lgName"],
                            line=dict(width=1, color=TH.T["mute"]))
        if ch["sh"]:
            fig.add_scatter(x=ch["t"], y=ch["sh"], name=ch["shName"],
                            line=dict(width=1, color=TH.T["faint"]),
                            line_dash="dot")
        fig.add_scatter(x=ch["t"], y=ch["sp"], name="spread",
                        line=dict(width=2.2, color=TH.T["teal"]))
        fig.update_layout(height=250, hovermode="x unified",
                          xaxis=TH.thin_ticks(ch["t"]))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})

    # -------------------------------------------------------- persistence
    if field.get("persist"):
        TH.ctitle("Holds across windows")
        TH.caption("Nine windows agreeing is the only evidence here that a "
                   "relationship is structural rather than a fortnight of luck.")
        st.dataframe(
            pd.DataFrame(field["persist"])[
                ["label", "kind", "count", "best", "avgRank",
                 "medSharpe", "medER"]],
            hide_index=True, use_container_width=True, row_height=30)

    # -------------------------------------------------------------- digest
    # st.code ships a copy button, so the whole window can be lifted in one
    # click. Selecting by hand triggers Streamlit's "C" shortcut and clears
    # the cache instead.
    TH.ctitle("Digest", "copy button, top right")
    lines = [f"SAKATA · {window} · {w['note']}",
             f"{w['start']} to {w['end']} · {w['bars']} bars · "
             f"{w['instruments']} instruments",
             f"Sharpe SE ±{w['se']} — treat anything under {w['noise']} as noise",
             f"Field {w['nField']} ({w['nOut']} outright, {w['nPair']} pairs, "
             f"{w['nCapped']} capped on ratio)",
             f"Median Sharpe: outright {w['medOut']}, pair {w['medPair']}",
             f"Best outright {w['bestOut']} at rank {w['outRank']}",
             ""]
    for r in w["rows"][:15]:
        pos = (f"{r['long']}/{r['short']}" if r["long"] and r["short"]
               else f"long {r['long']}" if r["long"] else f"short {r['short']}")
        lines.append(f"{r['n']:>3}  {pos:<12} {r['kind']:<8} "
                     f"Sharpe {r['sharpe']:>6}  ER {r['er']:>6}  "
                     f"tot {r['tot']:>6}%  vol {r['vol']:>5}%")
    st.code("\n".join(lines), language=None)
