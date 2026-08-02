"""Sakata — futures terminal. Thin launcher: theme, header, tab wiring."""
import datetime as dt
from urllib.parse import quote

import streamlit as st

from board import render_board
from technical import render_ta
from spreads import render_spreads_tab
from portfolio import render_portfolio_tab
from margins import render_margins
from events import render_events
from news import render_news
from curve import render_curve


# ------------------------------------------------------------------ canvas art
# Two families of parallel bezier curves — contour lines, not a chart. Built in
# Python and inlined as a data URI so there is no extra file to serve and no
# hand-encoding of the SVG.
_CURVE_TOP = "M-160 300C140 168 384 432 700 300S1180 120 1600 246"
_CURVE_BOT = "M-160 626C200 520 300 764 680 660S1150 516 1600 608"
_CURVE_MID = "M-160 470C220 400 420 560 780 470S1220 380 1600 452"


def _band(path: str, count: int, step: int, op0: float, dop: float,
          width: float = 1.1) -> str:
    return "".join(
        f'<path d="{path}" transform="translate(0 {i * step})" '
        f'stroke-width="{width}" opacity="{max(op0 - i * dop, 0.015):.3f}"/>'
        for i in range(count)
    )


_BG_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 900" '
    'preserveAspectRatio="xMidYMid slice">'
    '<g fill="none" stroke="#0f766e" stroke-linecap="round">'
    + _band(_CURVE_TOP, 11, 27, 0.135, 0.010)
    + _band(_CURVE_MID, 5, 34, 0.055, 0.008, 0.9)
    + _band(_CURVE_BOT, 9, 31, 0.115, 0.011)
    + f'<path d="{_CURVE_TOP}" stroke="#0d9488" stroke-width="1.9" opacity="0.20"/>'
    + f'<path d="{_CURVE_BOT}" stroke="#0d9488" stroke-width="1.7" opacity="0.17"/>'
    '</g></svg>'
)
_BG_URI = "data:image/svg+xml;charset=utf-8," + quote(_BG_SVG, safe="")


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {{
  --sk-sans:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  --sk-mono:'IBM Plex Mono',ui-monospace,'SF Mono',Menlo,monospace;
  --sk-ink:#0f172a; --sk-body:#334155; --sk-mute:#64748b; --sk-faint:#94a3b8;
  --sk-line:#e3e9ee; --sk-hair:#f1f5f9; --sk-teal:#0f766e; --sk-pos:#15803d;
  --sk-neg:#be123c;
}}

html, body, [data-testid="stAppViewContainer"], .stMarkdown,
.stButton, input, textarea, select, [data-baseweb], [class*="st-"] {{
  font-family: var(--sk-sans) !important;
}}

/* ------------------------------------------------------------ page canvas */
.stApp {{ background:#f6f9f8 !important; }}
.stApp::before {{ content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
  background-image:url("{_BG_URI}"); background-size:cover;
  background-position:center; background-repeat:no-repeat; }}
.stApp::after {{ content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
  background:radial-gradient(120% 90% at 50% 0%, rgba(255,255,255,0.92) 0%,
             rgba(255,255,255,0.55) 45%, rgba(255,255,255,0.18) 100%); }}
[data-testid="stAppViewContainer"], [data-testid="stHeader"],
[data-testid="stAppViewContainer"] > .main {{ background:transparent !important; }}
.block-container {{ position:relative; z-index:1; padding-top:1.9rem;
  padding-bottom:2.4rem; max-width:1080px; }}

/* ---------------------------------------------------------------- header */
.sakata-head {{ position:relative; overflow:hidden; display:flex; align-items:center;
  gap:14px; padding:15px 20px; margin:0 0 18px; border-radius:12px;
  border:1px solid rgba(45,212,191,0.22);
  box-shadow:0 6px 22px -14px rgba(15,23,42,0.55);
  background:
    radial-gradient(130% 180% at 86% 15%, rgba(16,185,129,0.22), transparent 62%),
    linear-gradient(135deg, #0a1512 0%, #0f172a 55%, #0b1220 100%); }}
.sakata-head::before {{ content:""; position:absolute; inset:0; pointer-events:none;
  background-image:
    linear-gradient(rgba(45,212,191,0.085) 1px, transparent 1px),
    linear-gradient(90deg, rgba(45,212,191,0.085) 1px, transparent 1px);
  background-size:24px 24px;
  -webkit-mask-image:linear-gradient(90deg, transparent 0%, #000 30%, #000 100%);
  mask-image:linear-gradient(90deg, transparent 0%, #000 30%, #000 100%); }}
.sakata-art {{ position:absolute; right:0; top:0; height:100%; width:64%;
  pointer-events:none;
  -webkit-mask-image:linear-gradient(90deg, transparent 0%, #000 45%, #000 100%);
  mask-image:linear-gradient(90deg, transparent 0%, #000 45%, #000 100%); }}
.sakata-mark, .sakata-word, .sakata-meta {{ position:relative; z-index:1; }}
.sakata-word {{ display:flex; flex-direction:column; gap:3px; line-height:1; }}
.sakata-title {{ font-size:1rem; font-weight:600; letter-spacing:0.24em;
  color:#f1f5f9; }}
.sakata-tag {{ font-size:9px; font-weight:600; letter-spacing:0.17em;
  text-transform:uppercase; color:#5eead4; opacity:0.82; }}
.sakata-meta {{ margin-left:auto; display:flex; align-items:center; gap:8px;
  font-family:var(--sk-mono) !important; font-size:10.5px; font-weight:500;
  letter-spacing:0.06em; color:#94a3b8; text-transform:uppercase; }}
.sakata-dot {{ width:6px; height:6px; border-radius:50%; background:#34d399;
  animation:sakata-pulse 2.6s ease-out infinite; }}
@keyframes sakata-pulse {{
  0%   {{ box-shadow:0 0 0 0 rgba(52,211,153,0.55); }}
  70%  {{ box-shadow:0 0 0 7px rgba(52,211,153,0); }}
  100% {{ box-shadow:0 0 0 0 rgba(52,211,153,0); }} }}

/* ------------------------------------------------------------------ tabs */
.stTabs [data-baseweb="tab-list"] {{ gap:2px; border-bottom:1px solid var(--sk-line);
  flex-wrap:wrap; }}
.stTabs [data-baseweb="tab"] {{ height:36px; padding:0 15px; font-weight:500;
  font-size:12.5px; color:var(--sk-mute); letter-spacing:0.015em; }}
.stTabs [data-baseweb="tab"]:hover {{ color:var(--sk-teal); }}
.stTabs [aria-selected="true"] {{ color:var(--sk-teal); font-weight:600; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color:var(--sk-teal); height:2px; }}

/* eyebrow subheaders — small teal rule instead of a bare label */
.stMarkdown h5 {{ font-size:10px; text-transform:uppercase; letter-spacing:0.11em;
  color:var(--sk-mute); font-weight:600; margin:14px 0 6px;
  display:flex; align-items:center; gap:8px; }}
.stMarkdown h5::before {{ content:""; width:14px; height:2px; border-radius:1px;
  background:var(--sk-teal); opacity:0.75; }}

/* buttons */
.stButton>button {{ border:1px solid var(--sk-line); border-radius:6px; padding:2px 15px;
  font-size:10.5px; font-weight:600; letter-spacing:0.07em; text-transform:uppercase;
  color:var(--sk-mute); background:#fff; box-shadow:none; transition:all .12s;
  min-height:30px; }}
.stButton>button:hover {{ border-color:var(--sk-teal); color:var(--sk-teal);
  background:#f0fdfa; }}
.stButton>button:active, .stButton>button:focus {{ color:var(--sk-teal);
  border-color:var(--sk-teal); box-shadow:none; }}

/* captions + controls */
[data-testid="stCaptionContainer"] {{ color:var(--sk-mute); font-size:11.5px;
  line-height:1.6; }}
.stRadio [role="radiogroup"] label {{ font-size:12px; color:var(--sk-body);
  font-weight:500; }}

/* ---------------------------------------------------------------- tables */
/* the container is the card; the table inside stays flush to its edges */
[data-testid="stTable"] {{ width:100%; overflow:hidden; background:#fff;
  border:1px solid var(--sk-line); border-radius:9px;
  box-shadow:0 1px 2px rgba(15,23,42,0.04); }}
[data-testid="stTable"] table {{ width:100%; font-size:12px; border-collapse:collapse;
  font-variant-numeric:tabular-nums; line-height:1.45; }}
[data-testid="stTable"] thead th {{ background:#fbfcfd; color:var(--sk-faint);
  font-family:var(--sk-sans) !important; font-weight:600; text-transform:uppercase;
  font-size:9.5px; letter-spacing:0.08em; border-bottom:1px solid var(--sk-line);
  padding:8px 12px !important; text-align:right; }}
[data-testid="stTable"] thead th:first-child,
[data-testid="stTable"] tbody th {{ text-align:left; }}
/* figures in mono, labels in sans — the single biggest readability lever */
[data-testid="stTable"] td {{ font-family:var(--sk-mono) !important; font-size:11.5px;
  font-weight:500; padding:5px 12px !important;
  border-bottom:1px solid var(--sk-hair); text-align:right; white-space:nowrap;
  color:var(--sk-body); }}
[data-testid="stTable"] td:first-child {{ font-family:var(--sk-sans) !important;
  font-size:12px; text-align:left; font-weight:500; color:var(--sk-ink);
  padding-right:18px !important; letter-spacing:-0.005em; }}
[data-testid="stTable"] tbody tr:last-child td {{ border-bottom:none; }}
[data-testid="stTable"] tbody tr:hover td {{ background:#f6fbfa; }}
[data-testid="stDataFrame"] {{ font-size:12.5px; border:1px solid var(--sk-line);
  border-radius:9px; }}
hr {{ margin:0.7rem 0; border-color:var(--sk-hair); }}

/* two-up board panels — fill the column, tighter gutters */
[data-testid="stHorizontalBlock"] [data-testid="stTable"] th,
[data-testid="stHorizontalBlock"] [data-testid="stTable"] td {{
  padding:4px 8px !important; }}
[data-testid="stHorizontalBlock"] [data-testid="stTable"] td:first-child {{
  padding-right:8px !important; }}
[data-testid="stHorizontalBlock"] [data-testid="stTable"] td {{ font-size:11px; }}
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
