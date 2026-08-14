"""Sakata — the look, ported from sakata.css to Streamlit.

The tokens are the same ones declared in site/sakata.css. They are repeated
here rather than parsed out of that file because Streamlit needs them as
Python values for the Plotly template as well as as CSS, and a parser that
silently returns the wrong colour is worse than a duplicate that is visibly
wrong. If a token changes in sakata.css, change it here too.

Dark only for now. The light set is in sakata.css if a switch is ever wanted;
Streamlit's own theming cannot flip at runtime without a rerun, so it would be
a config change rather than a header button.
"""
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ------------------------------------------------------------------ tokens
T = {
    "bg": "#0b0f12", "surface": "#11171b", "raised": "#161d22",
    "line": "#232c33", "hair": "#1a2229",
    "ink": "#e9eff2", "body": "#b6c2c9", "mute": "#8b979f", "faint": "#68757d",
    "teal": "#2dd4bf", "teal_b": "#5eead4", "teal_d": "#8ff0e2",
    "pos": "#34d3a8", "neg": "#f0736a", "amber": "#d3a355",
    "grid": "#1a2229", "axis": "#2b353d",
    "up": "#2dd4bf", "down": "#f0736a",
}
SANS = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"

# Sector identity, muted by design so a tag can never read as a signal.
SECTOR = {
    "Indices": "#6f9fd8", "Bonds": "#8fa9bf", "Currencies": "#a596d6",
    "Crypto": "#5fb8ac", "Energy": "#c08360", "Metals": "#d0ae6b",
    "Grains": "#a5b96f", "Softs": "#6bb9a4",
}

_CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;450;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"] {{
  font-family: {SANS};
  font-feature-settings: 'tnum' 1, 'lnum' 1;
}}

/* Kill Streamlit's default top padding — the header lockup is ours. */
.block-container {{ max-width: 1160px; padding: 1.6rem 1.5rem 4rem; }}
#MainMenu, footer {{ visibility: hidden; }}

/* ---------------------------------------------------------- header lockup */
.sk-head {{
  display: flex; align-items: center; gap: 10px; margin: 0 0 14px;
}}
.sk-mark {{ flex: none; color: {T['teal']}; margin-bottom: 2px; }}
.sk-word {{
  font-size: 23px; font-weight: 800; letter-spacing: -.035em;
  color: {T['ink']}; margin: 0; line-height: 1;
}}
.sk-rule {{ flex: 1; height: 1px; background: {T['line']}; margin: 2px 4px 0; }}
.sk-stamp {{
  font-family: {MONO}; font-size: 11px; color: {T['faint']};
  white-space: nowrap; letter-spacing: -.02em;
}}

/* ------------------------------------------------------------------ tabs */
.stTabs [data-baseweb="tab-list"] {{
  gap: 0; border-bottom: 1px solid {T['line']};
}}
.stTabs [data-baseweb="tab"] {{
  padding: 10px 14px 9px; font-size: 12px; font-weight: 600;
  letter-spacing: .06em; text-transform: uppercase; color: {T['mute']};
}}
.stTabs [aria-selected="true"] {{ color: {T['teal']}; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: {T['teal']}; }}

/* ---------------------------------------------------------------- tables */
[data-testid="stDataFrame"] {{ font-size: 13px; }}
[data-testid="stDataFrame"] thead th {{
  font-size: 10.5px !important; font-weight: 600 !important;
  text-transform: uppercase; letter-spacing: .08em; color: {T['faint']} !important;
}}

/* --------------------------------------------------------------- metrics */
[data-testid="stMetricLabel"] {{
  font-size: 10.5px !important; font-weight: 600; text-transform: uppercase;
  letter-spacing: .08em; color: {T['faint']};
}}
[data-testid="stMetricValue"] {{
  font-size: 21px !important; font-weight: 700; letter-spacing: -.02em;
  color: {T['ink']};
}}

/* -------------------------------------------------------------- controls */
.stRadio [role="radiogroup"] {{ gap: 2px; flex-wrap: wrap; }}
.stButton button {{
  font-size: 13px; font-weight: 500; border-radius: 3px;
  border: 1px solid {T['line']}; background: {T['surface']}; color: {T['body']};
}}
.stButton button:hover {{ border-color: {T['teal']}; color: {T['teal']}; }}

/* Chart titles: rendered as markdown so they sit above the plot rather than
   colliding with Plotly's legend, which is what the default does. */
.sk-ctitle {{
  font-size: 12.5px; font-weight: 600; color: {T['ink']};
  margin: 14px 0 -4px; padding: 0 2px;
}}
.sk-ctitle span {{ font-size: 11px; font-weight: 400; color: {T['faint']}; }}
.sk-caption {{ font-size: 12.5px; color: {T['mute']}; margin: 0 0 10px; }}
</style>
"""

_MARK = """
<svg class="sk-mark" width="26" height="32" viewBox="0 0 26 32" fill="none">
<path d="M13 31V13" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>
<path d="M13 22.5c0-3.4 2-5.6 5.6-6-.1 3.5-2 5.7-5.6 6z" fill="currentColor"/>
<path d="M13 22.5c0-3.4-2-5.6-5.6-6 .1 3.5 2 5.7 5.6 6z" fill="currentColor"/>
<path d="M13 15.5c0-3.4 2-5.6 5.6-6-.1 3.5-2 5.7-5.6 6z" fill="currentColor" opacity=".72"/>
<path d="M13 15.5c0-3.4-2-5.6-5.6-6 .1 3.5 2 5.7 5.6 6z" fill="currentColor" opacity=".72"/>
<path d="M13 9c0-3.1 1.6-5 4.6-5.6C17.5 6.5 16 8.4 13 9z" fill="currentColor" opacity=".45"/>
<path d="M13 9c0-3.1-1.6-5-4.6-5.6C8.5 6.5 10 8.4 13 9z" fill="currentColor" opacity=".45"/>
</svg>
"""


def apply(stamp: str = "") -> None:
    """Inject the CSS and draw the header lockup. Call once, at the top."""
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="sk-head">{_MARK}'
        f'<h1 class="sk-word">Sakata</h1>'
        f'<span class="sk-rule"></span>'
        f'<span class="sk-stamp">{stamp}</span></div>',
        unsafe_allow_html=True)
    _register_template()


def _register_template() -> None:
    """A Plotly template built from the same tokens, set as the default."""
    pio.templates["sakata"] = go.layout.Template(layout=go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=SANS, size=11, color=T["mute"]),
        xaxis=dict(showgrid=False, linecolor=T["axis"], zeroline=False,
                   tickfont=dict(size=10.5, color=T["faint"]), tickangle=0),
        yaxis=dict(gridcolor=T["grid"], linecolor=T["axis"], zeroline=False,
                   tickfont=dict(size=10.5, color=T["faint"])),
        legend=dict(orientation="h", yanchor="top", y=-0.16, x=0,
                    font=dict(size=11, color=T["mute"])),
        hoverlabel=dict(bgcolor=T["surface"], bordercolor=T["line"],
                        font=dict(family=SANS, size=12, color=T["ink"])),
        margin=dict(l=8, r=8, t=6, b=8),
    ))
    pio.templates.default = "sakata"


def ctitle(text: str, sub: str = "") -> None:
    """A chart heading in the Sakata register: name left, stats faint right."""
    tail = f' <span>{sub}</span>' if sub else ""
    st.markdown(f'<div class="sk-ctitle">{text}{tail}</div>',
                unsafe_allow_html=True)


def caption(text: str) -> None:
    st.markdown(f'<div class="sk-caption">{text}</div>', unsafe_allow_html=True)


def thin_ticks(labels, target: int = 8) -> dict:
    """Category axes draw every label and then stack them vertically. Step the
    ticks instead so the axis reads horizontally at any window length."""
    step = max(1, len(labels) // target)
    return dict(type="category", tickmode="array",
                tickvals=list(labels[::step]), tickangle=0)
