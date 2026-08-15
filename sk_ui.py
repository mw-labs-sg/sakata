"""Sakata — the UI layer, ported from core.js.

sakata.css is loaded from site/ and injected verbatim. That matters: the whole
point of the token system is that every colour is declared once, and a Python
copy of the palette would be a second place to get it wrong. The SVG charts
need the values as Python strings, so they are parsed back out of the same
file — which is exactly what core.js does through getComputedStyle.

Streamlit's own chrome is bridged on top: its containers are given the Sakata
ground, its tab strip is restyled to match, and its default padding removed.
"""
import html as _html
import re
from pathlib import Path

import streamlit as st

CSS_PATH = Path(__file__).parent / "site" / "sakata.css"
W = 1100          # nominal SVG width; viewBox scales it to the container


# ------------------------------------------------------------------ tokens
def _block(css: str, selector: str) -> dict:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.S)
    if not m:
        return {}
    return {k: v.strip() for k, v in
            re.findall(r"--([\w-]+)\s*:\s*([^;]+);", m.group(1))}


@st.cache_data
def _load_css() -> str:
    try:
        return CSS_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def tokens(dark: bool = True) -> dict:
    css = _load_css()
    t = _block(css, ":root")
    if dark:
        t.update(_block(css, ':root[data-theme="dark"]'))
    return t


# Resolved at import for the default theme; apply() refreshes on a flip.
C = {}
SECTOR_COL = {}
BIAS_COL = {}


def _palette(dark: bool) -> None:
    """The same mapping core.js builds, minus the getComputedStyle round trip."""
    t = tokens(dark)

    def v(name, fb):
        return t.get(name, fb)

    C.clear()
    C.update({
        "pos": v("pos", "#0a7c66"), "neg": v("neg", "#c2453b"),
        "up": v("up", "#0d9488"), "down": v("down", "#cf5a54"),
        "teal": v("teal", "#0d8f83"), "deep": v("teal-d", "#0d5f58"),
        "line": v("line", "#e0e5e8"), "grid": v("grid", "#eef1f3"),
        "amber": v("amber", "#96701c"), "mute": v("mute", "#66727b"),
        "faint": v("faint", "#97a2ab"), "axis": v("axis", "#d3dade"),
        "volbar": v("volbar", "#e9edf1"), "other": v("sec-other", "#9aa2ab"),
        "ink": v("ink", "#0d1418"), "bg": v("bg", "#f4f6f7"),
        "surface": v("surface", "#ffffff"),
    })
    SECTOR_COL.clear()
    SECTOR_COL.update({
        "Indices": v("sec-indices", "#3b6ea5"), "Bonds": v("sec-bonds", "#5c7d99"),
        "Currencies": v("sec-currencies", "#7a6ba8"),
        "Crypto": v("sec-crypto", "#4c8f86"), "Energy": v("sec-energy", "#8c5a3c"),
        "Metals": v("sec-metals", "#a8894f"), "Grains": v("sec-grains", "#7d8f4e"),
        "Softs": v("sec-softs", "#4f8f7d"),
    })
    BIAS_COL.clear()
    BIAS_COL.update({
        "3": v("bias3", "#0d5f58"), "2": v("bias2", "#0d9488"),
        "1": v("bias1", "#5fbcb1"), "0": v("bias0", "#9aa4ad"),
        "-1": v("biasn1", "#dda29e"), "-2": v("biasn2", "#cf5a54"),
        "-3": v("biasn3", "#a33f3a"),
    })


_palette(True)


# -------------------------------------------------------------- injection
_FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
          '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
          '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@'
          '400;450;500;600;700;800&family=JetBrains+Mono:wght@400;500'
          '&display=swap" rel="stylesheet">')


def _bridge(t: dict) -> str:
    """Streamlit's own chrome, dressed in the same tokens."""
    return f"""
.stApp {{ background: {t.get('bg')}; }}
.block-container {{ max-width: 1160px; padding: 20px 24px 56px; }}
#MainMenu, footer, header[data-testid="stHeader"] {{ display: none; }}
.stApp, .stApp * {{ font-family: var(--sans) !important; }}
.sk-stamp, code, pre, pre * {{ font-family: var(--mono) !important; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 0; border-bottom: 1px solid {t.get('line')}; background: transparent; }}
.stTabs [data-baseweb="tab"] {{ padding: 10px 15px 9px; }}
/* The label is a nested <p>, and Streamlit sets text-transform on it. A rule
   on the button alone is inherited and then overridden, so target the p. */
.stTabs [data-baseweb="tab"] p, .stTabs [data-baseweb="tab"] {{ font-size: 11.5px !important; font-weight: 650 !important; letter-spacing: .1em !important; text-transform: uppercase !important; color: {t.get('mute')}; }}
.stTabs [aria-selected="true"] p, .stTabs [aria-selected="true"] {{ color: {t.get('teal')} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: {t.get('teal')}; }}
.stTabs [data-baseweb="tab-border"] {{ display: none; }}
.stSelectbox div[data-baseweb="select"] > div {{ background: {t.get('surface')}; border-color: {t.get('line')}; font-size: 13px; }}
.stRadio [role="radiogroup"] {{ gap: 4px; flex-wrap: wrap; }}
/* Icon buttons: square, quiet, teal on hover — the header switches from
   index.html, minus the SVG. */
.stButton button {{ width: 32px; height: 30px; min-height: 30px; padding: 0; font-size: 14px; line-height: 1; border-radius: 4px; border: 1px solid {t.get('line')}; background: {t.get('surface')}; color: {t.get('mute')}; transition: color .15s, border-color .15s; }}
.stButton button p {{ font-size: 14px !important; margin: 0 !important; }}
.stButton button:hover, .stButton button:focus {{ border-color: {t.get('teal')}; color: {t.get('teal')} !important; box-shadow: none; }}
.stButton button:hover p {{ color: {t.get('teal')} !important; }}
.sk-head {{ display: flex; align-items: center; gap: 10px; margin: 0 0 4px; }}
.sk-mark {{ flex: none; color: {t.get('teal')}; margin-bottom: 2px; }}
.sk-word {{ font-family: var(--display); font-size: 23px; font-weight: 800; letter-spacing: -.035em; color: {t.get('ink')}; margin: 0; line-height: 1; }}
.sk-rule {{ flex: 1; height: 1px; background: {t.get('line')}; margin: 2px 4px 0; }}
.sk-stamp {{ font-size: 11px; color: {t.get('faint')}; white-space: nowrap; letter-spacing: -.02em; }}
.chart {{ width: 100%; height: auto; }}
"""


MARK = ('<svg class="sk-mark" width="26" height="32" viewBox="0 0 26 32" '
        'fill="none">'
        '<path d="M13 31V13" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
        '<path d="M13 22.5c0-3.4 2-5.6 5.6-6-.1 3.5-2 5.7-5.6 6z" fill="currentColor"/>'
        '<path d="M13 22.5c0-3.4-2-5.6-5.6-6 .1 3.5 2 5.7 5.6 6z" fill="currentColor"/>'
        '<path d="M13 15.5c0-3.4 2-5.6 5.6-6-.1 3.5-2 5.7-5.6 6z" fill="currentColor" opacity=".72"/>'
        '<path d="M13 15.5c0-3.4-2-5.6-5.6-6 .1 3.5 2 5.7 5.6 6z" fill="currentColor" opacity=".72"/>'
        '<path d="M13 9c0-3.1 1.6-5 4.6-5.6C17.5 6.5 16 8.4 13 9z" fill="currentColor" opacity=".45"/>'
        '<path d="M13 9c0-3.1-1.6-5-4.6-5.6C8.5 6.5 10 8.4 13 9z" fill="currentColor" opacity=".45"/>'
        '</svg>')


def md(s: str) -> None:
    """Emit raw HTML. Blank lines must go: markdown ends a raw-HTML block at
    the first empty line and renders everything after it as text."""
    st.markdown("\n".join(ln for ln in s.splitlines() if ln.strip()),
                unsafe_allow_html=True)


def apply(dark: bool = True) -> None:
    """Inject fonts, sakata.css and the Streamlit bridge."""
    _palette(dark)
    t = tokens(dark)
    css = _load_css()
    if dark:
        # sakata.css scopes dark to :root[data-theme], which we cannot set on
        # documentElement without JS. Re-declaring the block on :root is the
        # same result with no script.
        css += "\n:root{" + "".join(f"--{k}:{v};" for k, v in
                                    _block(css, ':root[data-theme="dark"]').items()) + "}"
    md(_FONTS + "<style>" + css + _bridge(t) + "</style>")


def header(stamp: str = "") -> None:
    """The lockup: mark, wordmark, hairline, stamp — all on one line.

    Everything here is an inline style on a span. Streamlit's own rules for
    <h1> and for its markdown container are specific enough to win against a
    class, which is what pushed the mark onto its own line and stripped the
    teal off it.
    """
    t = tokens(st.session_state.get("dark", True))
    md(f'<div style="display:flex;align-items:center;gap:11px;margin:0 0 2px">'
       f'<span style="flex:none;line-height:0;color:{t.get("teal")}">{MARK}</span>'
       f'<span style="font-family:var(--display),Inter,sans-serif;font-size:27px;'
       f'font-weight:800;letter-spacing:-.035em;color:{t.get("ink")};'
       f'line-height:1">Sakata</span>'
       f'<span style="flex:1;height:1px;background:{t.get("line")};'
       f'margin-top:3px"></span>'
       f'<span style="font-size:11px;color:{t.get("faint")};white-space:nowrap;'
       f'letter-spacing:-.02em">{esc(stamp)}</span></div>')


# ------------------------------------------------------------ tiny helpers
def esc(s) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def num(v, d=2):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f"{f:,.{d}f}"


def pct(v, d=2) -> str:
    n = num(v, d)
    if n is None:
        return '<td class="faint">—</td>'
    sign = "+" if float(v) >= 0 else ""
    cls = "pos" if float(v) >= 0 else "neg"
    return f'<td class="{cls}">{sign}{n}</td>'


def cell(v, d=2, cls="") -> str:
    n = num(v, d)
    if n is None:
        return '<td class="faint">—</td>'
    return f'<td class="{cls}">{n}</td>'


def table(head: str, body: str) -> str:
    return (f'<div class="card scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def swatch(sec: str) -> str:
    return f'<i class="sw" style="background:{SECTOR_COL.get(sec, C["other"])}"></i>'


def eyebrow(text: str, extra: str = "") -> str:
    return f'<div class="eyebrow">{esc(text)}{extra}</div>'


def note(html_text: str) -> str:
    return f'<div class="note">{html_text}</div>'


def chips(items) -> str:
    return ('<div class="chips">' +
            "".join(f'<span class="chip">{esc(c)}</span>' for c in items) +
            "</div>")


def age_text(mins) -> str:
    if mins is None:
        return ""
    if mins < 2:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    h = mins // 60
    return f"{h}h ago" if h < 24 else f"{h // 24}d ago"
