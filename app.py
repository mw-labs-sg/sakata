"""Sakata on Streamlit — Board spike.

The point of this file is NOT the Board. It is the diagnostic underneath it:
does Yahoo serve Streamlit Cloud's IP range for all 19 tickers, at 15m and 1h
as well as daily? That is the single assumption the whole migration rests on.
If any interval comes back short here, stop and rethink before porting more.
"""
import pandas as pd
import streamlit as st

import sk_board as BOARD
import sk_sources as S
import sk_universe as U

st.set_page_config(page_title="Sakata", layout="wide")
S.DRY = False


@st.cache_data(ttl=300, show_spinner="fetching prices…")
def prices(interval: str, period: str) -> dict:
    """Cached for 5 minutes so widget clicks don't refetch."""
    return S.fetch_ohlc(interval, period)


st.title("Sakata")

if st.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

# ------------------------------------------------------------------ board
daily = prices("1d", "10y")
if not daily:
    st.error("No daily data at all — Yahoo returned nothing.")
    st.stop()

rows = BOARD.build_board(daily)["rows"]
df = pd.DataFrame(rows)

for group in U.GROUPS:
    sub = df[df["group"] == group]
    if sub.empty:
        continue
    st.subheader(group)
    st.dataframe(
        sub[["code", "name", "sector", "last", "Day", "WTD", "MTD", "QTD", "YTD"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            c: st.column_config.NumberColumn(c, format="%.2f%%")
            for c in ("Day", "WTD", "MTD", "QTD", "YTD")
        },
    )

# ------------------------------------------------------- the real test
st.divider()
st.subheader("Fetch diagnostic")
st.caption("Every interval should show 19/19. Anything less means Yahoo is "
           "throttling this IP range and the migration needs a rethink.")

checks = []
for label, interval, period in [("15-minute", "15m", "60d"),
                                ("hourly", "1h", "730d"),
                                ("daily", "1d", "10y")]:
    got = prices(interval, period)
    missing = [c for c in U.CODES if c not in got or got[c] is None or got[c].empty]
    checks.append({
        "interval": label,
        "got": f"{len(U.CODES) - len(missing)}/{len(U.CODES)}",
        "bars (ES)": len(got.get("ES", [])),
        "last bar": (str(got["ES"].index[-1]) if "ES" in got and len(got["ES"])
                     else "—"),
        "missing": ", ".join(missing) if missing else "none",
    })

st.dataframe(pd.DataFrame(checks), hide_index=True, use_container_width=True)
