"""Board tab — sector scanner, financials and commodities side by side."""
import altair as alt
import pandas as pd
import streamlit as st

from common import SECTORS, GROUPS, GROUP_OF, get_perf

HORIZONS = ["Day", "WTD", "MTD", "QTD", "YTD"]
_KEYS = {"Day": "day", "WTD": "wtd", "MTD": "mtd", "QTD": "qtd", "YTD": "ytd"}

POS, NEG = "#15803d", "#be123c"

# Sector header rows: tinted band, teal spine on the first cell.
_HDR = ("background:#f0fdfa;color:#0f766e;font-weight:600;font-size:9.5px;"
        "text-transform:uppercase;letter-spacing:0.1em;"
        "font-family:'IBM Plex Sans',sans-serif;")
_SPINE = "box-shadow:inset 2px 0 0 #0d9488;"


def build_scanner() -> pd.DataFrame:
    rows = []
    for sector, members in SECTORS.items():
        for name, (ticker, dec) in members.items():
            p = get_perf(ticker)
            last = p.get("last")
            row = {
                "Instrument": " ".join(name.split()),
                "Sector": sector,
                "Group": GROUP_OF.get(sector, "Financials"),
                "Last": f"{last:,.{dec}f}" if last else "—",
            }
            for h in HORIZONS:
                row[h] = p.get(_KEYS[h], float("nan"))
            rows.append(row)
    return pd.DataFrame(rows)


def _fmt_pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{v:+.2f}"


def _panel_frame(df: pd.DataFrame, group: str):
    """Stack that group's sectors into one table, sector name as a header row."""
    rows, headers = [], set()
    for sec in [s for s in SECTORS if GROUP_OF.get(s) == group]:
        block = df[df["Sector"] == sec]
        if block.empty:
            continue
        headers.add(sec)
        rows.append({"Instrument": sec, "Last": "", **{h: "" for h in HORIZONS}})
        for _, r in block.iterrows():
            rows.append({
                "Instrument": "\u00a0\u00a0" + r["Instrument"],
                "Last": r["Last"],
                **{h: _fmt_pct(r[h]) for h in HORIZONS},
            })
    return pd.DataFrame(rows), headers


def _cell_colour(v):
    s = str(v)
    if s.startswith("+"):
        return f"color:{POS};font-weight:600;"
    if s.startswith("-"):
        return f"color:{NEG};font-weight:600;"
    return "color:#cbd5e1;"


def _render_panel(df: pd.DataFrame, group: str) -> None:
    frame, headers = _panel_frame(df, group)
    if frame.empty:
        st.caption("— no data")
        return

    def row_style(row):
        if row["Instrument"] not in headers:
            return [""] * len(row)
        return [_HDR + _SPINE] + [_HDR] * (len(row) - 1)

    st.table(
        frame.style
        .map(_cell_colour, subset=HORIZONS)
        .apply(row_style, axis=1)
        .hide(axis="index")
    )


def render_board() -> None:
    df = build_scanner()

    # controls row
    c1, c2 = st.columns([4, 1])
    with c1:
        hz = st.radio("Horizon", HORIZONS, index=0, horizontal=True,
                      label_visibility="collapsed")
    with c2:
        if st.button("Refresh", key="rb"):
            st.cache_data.clear()
            st.rerun()

    # --- sector performance: one chart across both groups, ranked ---
    st.markdown(f"##### Sector performance · {hz} %")
    agg = df.groupby(["Sector", "Group"], sort=False)[HORIZONS].mean().reset_index()
    agg["_v"] = agg[hz]
    agg = agg.sort_values("_v", ascending=False)
    bar = (alt.Chart(agg).mark_bar(cornerRadius=2, height=13).encode(
        x=alt.X("_v:Q", title=None,
                axis=alt.Axis(format="+.1f", grid=True, gridColor="#eef2f6",
                              domain=False, tickSize=0, labelFontSize=10,
                              labelFont="IBM Plex Mono")),
        y=alt.Y("Sector:N", sort=list(agg["Sector"]), title=None,
                axis=alt.Axis(labelFontSize=11, labelColor="#334155",
                              labelFont="IBM Plex Sans", domain=False, tickSize=0)),
        color=alt.condition("datum._v >= 0", alt.value(POS), alt.value(NEG)),
        tooltip=[alt.Tooltip("Sector:N"), alt.Tooltip("Group:N"),
                 alt.Tooltip("_v:Q", format="+.2f", title=hz)],
    ).properties(height=24 * len(agg) + 8)
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#94a3b8"))
    st.altair_chart(bar, use_container_width=True)

    # --- scanner: financials | commodities ---
    left, right = st.columns(2, gap="medium")
    for col, group in zip((left, right), GROUPS):
        with col:
            st.markdown(f"##### {group}")
            _render_panel(df, group)
