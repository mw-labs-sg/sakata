"""Sakata — futures terminal. Thin launcher: theme, header, tab wiring."""
import datetime as dt

import streamlit as st

from board import render_board
from technical import render_ta
from margins import render_margins
from events import render_events
from news import render_news
from curve import render_curve


_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"], .stMarkdown,
.stButton, input, textarea, select, [data-baseweb], [class*="st-"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
.block-container { padding-top: 2.4rem; padding-bottom: 2rem; max-width: 1060px; }

/* header */
.sakata-head { display:flex; align-items:center; gap:11px; border-bottom:2px solid #0f766e;
  padding-bottom:9px; margin-bottom:12px; }
.sakata-title { font-family:'Poppins',sans-serif !important; font-size:1.4rem; font-weight:700;
  letter-spacing:-0.01em; color:#0f172a; }
.sakata-sub { font-size:11px; color:#94a3b8; font-weight:500; letter-spacing:0.03em;
  margin-left:auto; text-transform:uppercase; }

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap:2px; border-bottom:1px solid #e5e7eb; }
.stTabs [data-baseweb="tab"] { height:38px; padding:0 20px; font-weight:600; font-size:13px;
  color:#64748b; letter-spacing:0.02em; }
.stTabs [aria-selected="true"] { color:#0f766e; }
.stTabs [data-baseweb="tab-highlight"] { background-color:#0f766e; height:2px; }

/* eyebrow subheaders */
.stMarkdown h5 { font-family:'Poppins',sans-serif !important; font-size:11px;
  text-transform:uppercase; letter-spacing:0.07em; color:#475569; font-weight:600;
  margin:10px 0 4px; }

/* buttons */
.stButton>button { border:1px solid #e2e8f0; border-radius:6px; padding:2px 15px;
  font-size:11px; font-weight:600; letter-spacing:0.05em; text-transform:uppercase;
  color:#475569; background:#fff; box-shadow:none; transition:all .12s; min-height:30px; }
.stButton>button:hover { border-color:#0f766e; color:#0f766e; background:#f0fdfa; }
.stButton>button:active, .stButton>button:focus { color:#0f766e; border-color:#0f766e;
  box-shadow:none; }

/* captions + controls */
[data-testid="stCaptionContainer"] { color:#64748b; font-size:12px; line-height:1.5; }
.stRadio [role="radiogroup"] label { font-size:12.5px; color:#334155; font-weight:500; }

/* tables (st.table) — tight but comfortable terminal density */
[data-testid="stTable"] { width:100%; overflow-x:auto; }
[data-testid="stTable"] table { width:auto; min-width:70%; font-size:12px;
  border-collapse:collapse; font-variant-numeric:tabular-nums; line-height:1.35; }
[data-testid="stTable"] thead th { background:#f8fafc; color:#64748b; font-weight:600;
  text-transform:uppercase; font-size:10px; letter-spacing:0.04em;
  border-bottom:1px solid #e2e8f0; padding:6px 12px !important; text-align:right; }
[data-testid="stTable"] thead th:first-child,
[data-testid="stTable"] tbody th { text-align:left; }
[data-testid="stTable"] td { padding:4px 12px !important; border-bottom:1px solid #f4f6f8;
  text-align:right; white-space:nowrap; color:#334155; }
[data-testid="stTable"] td:first-child { text-align:left; font-weight:500; color:#0f172a;
  padding-right:20px !important; }
[data-testid="stTable"] tbody tr:hover td { background:#f8fafc; }
[data-testid="stDataFrame"] { font-size:13px; border:1px solid #eef2f6; border-radius:8px; }
hr { margin:0.6rem 0; border-color:#eef2f6; }
</style>
"""

_LOGO = (
    '<svg width="30" height="30" viewBox="0 0 30 30" fill="none">'
    '<rect width="30" height="30" rx="7" fill="#0f172a"/>'
    # commodity bars (amber)
    '<rect x="6.5" y="17" width="3" height="7" rx="1" fill="#f59e0b"/>'
    '<rect x="13.5" y="14" width="3" height="10" rx="1" fill="#f59e0b"/>'
    '<rect x="20.5" y="11" width="3" height="13" rx="1" fill="#f59e0b"/>'
    # financial trend line (teal) weaving over the bars
    '<path d="M5 21 L11 13 L15 18 L19 9 L25 6" stroke="#2dd4bf" stroke-width="2.1" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="25" cy="6" r="2.1" fill="#2dd4bf"/>'
    '</svg>'
)


def main() -> None:
    st.set_page_config(page_title="Sakata", page_icon="🎋", layout="centered")
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="sakata-head">{_LOGO}'
        f'<span class="sakata-title">Sakata</span>'
        f'<span class="sakata-sub">futures terminal · {dt.datetime.now():%Y-%m-%d %H:%M}</span>'
        f'</div>', unsafe_allow_html=True)
    tab_board, tab_ta, tab_margins, tab_events, tab_news, tab_curve = st.tabs(
        ["Board", "Technical", "Margins", "Events", "News", "Curve"]
    )
    with tab_board:
        render_board()
    with tab_ta:
        render_ta()
    with tab_margins:
        render_margins()
    with tab_events:
        render_events()
    with tab_news:
        render_news()
    with tab_curve:
        render_curve()


if __name__ == "__main__":
    main()
