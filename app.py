"""Sakata — futures terminal. Thin launcher: theme, header, tab wiring."""
import datetime as dt

import streamlit as st

from board import render_board
from technical import render_ta
from spreads import render_spreads_tab
from portfolio import render_portfolio_tab
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
.block-container { padding-top: 1.9rem; padding-bottom: 2rem; max-width: 1060px; }

/* ---------------------------------------------------------------- header */
.sakata-head { position:relative; overflow:hidden; display:flex; align-items:center;
  gap:14px; padding:15px 20px; margin:0 0 18px; border-radius:12px;
  border:1px solid rgba(45,212,191,0.22);
  background:
    radial-gradient(130% 180% at 86% 15%, rgba(16,185,129,0.22), transparent 62%),
    linear-gradient(135deg, #0a1512 0%, #0f172a 55%, #0b1220 100%); }

/* faint field grid, fading in from the left */
.sakata-head::before { content:""; position:absolute; inset:0; pointer-events:none;
  background-image:
    linear-gradient(rgba(45,212,191,0.085) 1px, transparent 1px),
    linear-gradient(90deg, rgba(45,212,191,0.085) 1px, transparent 1px);
  background-size:24px 24px;
  -webkit-mask-image:linear-gradient(90deg, transparent 0%, #000 30%, #000 100%);
  mask-image:linear-gradient(90deg, transparent 0%, #000 30%, #000 100%); }

/* abstract price lines drifting across the right half */
.sakata-art { position:absolute; right:0; top:0; height:100%; width:64%;
  pointer-events:none;
  -webkit-mask-image:linear-gradient(90deg, transparent 0%, #000 45%, #000 100%);
  mask-image:linear-gradient(90deg, transparent 0%, #000 45%, #000 100%); }

.sakata-mark, .sakata-word, .sakata-meta { position:relative; z-index:1; }
.sakata-word { display:flex; flex-direction:column; gap:2px; line-height:1; }
.sakata-title { font-family:'Poppins',sans-serif !important; font-size:1.02rem;
  font-weight:700; letter-spacing:0.22em; color:#f1f5f9; }
.sakata-tag { font-size:9.5px; font-weight:600; letter-spacing:0.16em;
  text-transform:uppercase; color:#5eead4; opacity:0.8; }
.sakata-meta { margin-left:auto; display:flex; align-items:center; gap:8px;
  font-size:10.5px; font-weight:600; letter-spacing:0.09em; color:#94a3b8;
  text-transform:uppercase; font-variant-numeric:tabular-nums; }
.sakata-dot { width:6px; height:6px; border-radius:50%; background:#34d399;
  animation:sakata-pulse 2.6s ease-out infinite; }
@keyframes sakata-pulse {
  0%   { box-shadow:0 0 0 0 rgba(52,211,153,0.55); }
  70%  { box-shadow:0 0 0 7px rgba(52,211,153,0); }
  100% { box-shadow:0 0 0 0 rgba(52,211,153,0); } }

/* ------------------------------------------------------------------ tabs */
.stTabs [data-baseweb="tab-list"] { gap:2px; border-bottom:1px solid #e5e7eb;
  flex-wrap:wrap; }
.stTabs [data-baseweb="tab"] { height:38px; padding:0 16px; font-weight:600; font-size:13px;
  color:#64748b; letter-spacing:0.02em; }
.stTabs [data-baseweb="tab"]:hover { color:#0f766e; }
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

/* two-up board panels — fill the column, tighter gutters */
[data-testid="stHorizontalBlock"] [data-testid="stTable"] table {
  width:100%; min-width:0; }
[data-testid="stHorizontalBlock"] [data-testid="stTable"] th,
[data-testid="stHorizontalBlock"] [data-testid="stTable"] td {
  padding:3px 7px !important; }
[data-testid="stHorizontalBlock"] [data-testid="stTable"] td:first-child {
  padding-right:8px !important; }
</style>
"""

# Grain ear — stalk with three pairs of kernels. Reads as ag, not as a startup tile.
_MARK = (
    '<svg class="sakata-mark" width="26" height="30" viewBox="0 0 28 32" fill="none">'
    '<path d="M14 30V11" stroke="#34d399" stroke-width="1.7" stroke-linecap="round"/>'
    '<path d="M14 25c.2-2.9 1.9-4.4 5.3-4.6-.2 2.9-1.9 4.4-5.3 4.6z" fill="#34d399" '
    'opacity=".55"/>'
    '<path d="M14 25c-.2-2.9-1.9-4.4-5.3-4.6.2 2.9 1.9 4.4 5.3 4.6z" fill="#34d399" '
    'opacity=".55"/>'
    '<path d="M14 19.5c.2-2.9 1.9-4.4 5.3-4.6-.2 2.9-1.9 4.4-5.3 4.6z" fill="#2dd4bf" '
    'opacity=".75"/>'
    '<path d="M14 19.5c-.2-2.9-1.9-4.4-5.3-4.6.2 2.9 1.9 4.4 5.3 4.6z" fill="#2dd4bf" '
    'opacity=".75"/>'
    '<path d="M14 14c.2-2.9 1.9-4.4 5.3-4.6-.2 2.9-1.9 4.4-5.3 4.6z" fill="#5eead4"/>'
    '<path d="M14 14c-.2-2.9-1.9-4.4-5.3-4.6.2 2.9 1.9 4.4 5.3 4.6z" fill="#5eead4"/>'
    '<path d="M14 11.5V6" stroke="#5eead4" stroke-width="1.7" stroke-linecap="round"/>'
    '</svg>'
)

# Abstract tape running behind the wordmark.
_ART = (
    '<svg class="sakata-art" viewBox="0 0 420 80" preserveAspectRatio="xMaxYMid slice" '
    'fill="none">'
    '<path d="M0 30 L78 36 L148 22 L212 32 L286 18 L352 27 L420 15" stroke="#10b981" '
    'stroke-width="1" opacity=".18"/>'
    '<path d="M0 68 L62 54 L112 62 L172 36 L232 46 L292 20 L358 28 L420 10" '
    'stroke="#2dd4bf" stroke-width="1.5" opacity=".5" stroke-linejoin="round"/>'
    '<path d="M0 75 L70 70 L132 74 L200 60 L262 68 L332 50 L420 42" stroke="#34d399" '
    'stroke-width="1.1" opacity=".26" stroke-linejoin="round"/>'
    '<rect x="171" y="30" width="2.4" height="22" rx="1.2" fill="#2dd4bf" opacity=".22"/>'
    '<rect x="231" y="40" width="2.4" height="17" rx="1.2" fill="#2dd4bf" opacity=".18"/>'
    '<rect x="291" y="14" width="2.4" height="30" rx="1.2" fill="#5eead4" opacity=".28"/>'
    '<rect x="357" y="22" width="2.4" height="24" rx="1.2" fill="#2dd4bf" opacity=".2"/>'
    '<circle cx="292" cy="20" r="2.6" fill="#5eead4" opacity=".7"/>'
    '</svg>'
)


def _header() -> str:
    ts = f"{dt.datetime.now():%d %b %Y · %H:%M}"
    return (
        '<div class="sakata-head">'
        f'{_ART}{_MARK}'
        '<div class="sakata-word">'
        '<span class="sakata-title">SAKATA</span>'
        '<span class="sakata-tag">futures terminal</span>'
        '</div>'
        f'<div class="sakata-meta"><span class="sakata-dot"></span>{ts}</div>'
        '</div>'
    )


def main() -> None:
    st.set_page_config(page_title="Sakata", page_icon="🌾", layout="centered")
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(_header(), unsafe_allow_html=True)
    (tab_board, tab_ta, tab_spreads, tab_port, tab_margins,
     tab_events, tab_news, tab_curve) = st.tabs(
        ["Board", "Technical", "Spreads", "Portfolio", "Margins",
         "Events", "News", "Curve"]
    )
    with tab_board:
        render_board()
    with tab_ta:
        render_ta()
    with tab_spreads:
        render_spreads_tab(is_mobile=False)
    with tab_port:
        render_portfolio_tab(is_mobile=False)
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
