"""Board tab — sector scanner, financials and commodities side by side."""
import altair as alt
import pandas as pd
import streamlit as st

from common import SECTORS, GROUPS, GROUP_OF, get_perf

HORIZONS = ["Day", "WTD", "MTD", "QTD", "YTD"]
_KEYS = {"Day": "day", "WTD": "wtd", "MTD": "mtd", "QTD": "qtd", "YTD": "ytd"}

_HDR_STYLE = ("background:#f1f5f9;color:#0f766e;font-weight:700;font-size:10px;"
              "text-transform:uppercase;letter-spacing:0.06em;")


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
    return "—" if v is None or pd.isna(v) else f"{v:+.2f}%"


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
        return "color:#16a34a;font-weight:600;"
    if s.startswith("-"):
        return "color:#dc2626;font-weight:600;"
    return "color:#cbd5e1;"


def _render_panel(df: pd.DataFrame, group: str) -> None:
    frame, headers = _panel_frame(df, group)
    if frame.empty:
        st.caption("— no data")
        return

    def row_style(row):
        return [_HDR_STYLE if row["Instrument"] in headers else ""] * len(row)

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
    st.markdown(f"##### Sector performance · {hz}")
    agg = df.groupby(["Sector", "Group"], sort=False)[HORIZONS].mean().reset_index()
    agg["_v"] = agg[hz]
    agg = agg.sort_values("_v", ascending=False)
    bar = (alt.Chart(agg).mark_bar(cornerRadius=2, height=15).encode(
        x=alt.X("_v:Q", title=None, axis=alt.Axis(format="+.1f", grid=True,
                gridColor="#f1f5f9")),
        y=alt.Y("Sector:N", sort=list(agg["Sector"]), title=None,
                axis=alt.Axis(labelFontSize=12, labelColor="#334155")),
        color=alt.condition("datum._v >= 0", alt.value("#16a34a"), alt.value("#dc2626")),
        tooltip=[alt.Tooltip("Sector:N"), alt.Tooltip("Group:N"),
                 alt.Tooltip("_v:Q", format="+.2f", title=hz)],
    ).properties(height=26 * len(agg) + 10).configure_view(strokeWidth=0)
        .configure_axis(labelColor="#64748b"))
    st.altair_chart(bar, use_container_width=True)

    # --- scanner: financials | commodities ---
    left, right = st.columns(2, gap="medium")
    for col, group in zip((left, right), GROUPS):
        with col:
            st.markdown(f"##### {group}")
            _render_panel(df, group)
