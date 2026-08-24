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

# Offset of the theme switch from the top of .block-container, so it centres on
# the tab rule. Measured against the live DOM rather than guessed: the tab strip
# spans 72-113px inside the container, so its midline is 92.5, and the button is
# 30px tall — 92.5 - 15 = 78. The old 74px was tuned while the token-parser bug
# was dropping this whole stylesheet, against Streamlit's unstyled 96px padding,
# and left the switch 56px clear of the strip.
SWITCH_TOP = 78


# ------------------------------------------------------------------ tokens
def _declarations(body: str) -> dict:
    """{custom-property: value} for one CSS block, honouring quotes and parens.

    This cannot be a regex. `--caret` is a data: URL whose value contains a
    semicolon — url("data:image/svg+xml;charset=utf-8,…") — and the old
    `([^;]+);` value pattern stopped dead at it, keeping
    `url("data:image/svg+xml` with an unbalanced quote. apply() re-emits every
    token verbatim, so that one truncated value opened a string literal that
    ran to the end of the stylesheet and took the entire Streamlit bridge with
    it: dark mode parsed 124 rules where light mode got 168, and every bridge
    rule was silently dropped.

    A semicolon inside quotes or parens is content, not a terminator. Quotes
    also nest — the caret value carries fourteen single quotes inside its
    double-quoted URL — so only the matching delimiter closes a string.
    """
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    out, buf, quote, depth = {}, "", "", 0

    def keep(decl: str) -> None:
        k, sep, v = decl.partition(":")
        k = k.strip()
        if sep and k.startswith("--"):
            out[k[2:]] = v.strip()

    for ch in body:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == ";" and depth == 0:
            keep(buf)
            buf = ""
            continue
        buf += ch
    keep(buf)           # a trailing declaration needs no closing semicolon
    return out


def _block(css: str, selector: str) -> dict:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.S)
    return _declarations(m.group(1)) if m else {}


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


def _rgb(hexcol: str) -> tuple:
    """'#d3a355' -> (211, 163, 85). Falls back to a mid grey on anything odd."""
    h = str(hexcol).strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (150, 112, 28)


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
    # The bias ladder keeps its diverging shape but loses the red half. Three
    # amber steps carry -1/-2/-3 by intensity, so a short bias still reads as
    # stronger the further it goes without the score column looking like an
    # alarm. sakata.css keeps its own biasn tokens for the static site; this
    # only re-points the Python palette.
    ar, ag, ab = _rgb(C["amber"])

    def amber(alpha):
        return f"rgba({ar},{ag},{ab},{alpha})"

    BIAS_COL.clear()
    BIAS_COL.update({
        "3": v("bias3", "#0d5f58"), "2": v("bias2", "#0d9488"),
        "1": v("bias1", "#5fbcb1"), "0": v("bias0", "#9aa4ad"),
        "-1": amber(0.60), "-2": amber(0.82), "-3": amber(1),
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
    # The theme switch, addressed through the marker div app.py emits. Named
    # once because both the geometry and the position rule need it.
    sw = ('[data-testid="stElementContainer"]:has(#sk-theme-anchor) '
          '+ [data-testid="stElementContainer"]')
    return f"""
.stApp {{ background: {t.get('bg')}; }}
/* Streamlit bakes config.toml's textColor into its emotion classes and exposes
   no CSS variable to retarget it — there is not one custom property on :root,
   body, .stApp or stAppViewContainer — so the per-theme ink has to be set here
   or the light theme renders #e9eff2 on #f4f6f7 at 1.04:1 and the tab strip
   disappears. Buttons and the expander summary inherit from this rule; tabs,
   radios, the selectbox input and the code block each set colour explicitly
   and are handled next to their own rules below. */
body, .stApp {{ color: {t.get('body')} !important; }}
.block-container {{ max-width: 1160px; padding: 20px 24px 56px; }}
#MainMenu, footer, header[data-testid="stHeader"] {{ display: none; }}
.stApp, .stApp * {{ font-family: var(--sans) !important; }}
.sk-stamp, code, pre, pre * {{ font-family: var(--mono) !important; }}
/* Streamlit 1.59 draws the strip as [role="tablist"] with no testid, and each
   tab as [data-testid="stTab"]. The old [data-baseweb="tab-list"] selectors
   matched nothing: the strip kept its default 16px gap and drew no rule line.
   tab-highlight and tab-border are gone from the DOM entirely, so the rules
   for them are dropped rather than ported — the teal on the active tab comes
   from the aria-selected rule below. */
[role="tablist"] {{ gap: 0; border-bottom: 1px solid {t.get('line')}; background: transparent; }}
[data-testid="stTab"] {{ padding: 10px 15px 9px; }}
/* Caps come from Python now. This only handles size, weight and tracking, and
   is scoped to the strip: .stTabs button also caught every button inside a tab
   PANEL, which fought the 10.5px rule on Refresh. */
[role="tablist"] button, [role="tablist"] button *, [data-testid="stTab"], [data-testid="stTab"] * {{ font-size: 11.5px !important; font-weight: 650 !important; letter-spacing: .11em !important; }}
[data-testid="stTab"][aria-selected="false"], [data-testid="stTab"][aria-selected="false"] * {{ color: {t.get('mute')} !important; }}
[data-testid="stTab"][aria-selected="true"], [data-testid="stTab"][aria-selected="true"] * {{ color: {t.get('teal')} !important; }}
/* The source link is a footnote, not a call to action — teal, quiet, and set
   well clear of the date so the two do not read as one string. */
.news .mkt a {{ color: {t.get('teal')} !important; text-decoration: none; margin-left: 16px; font-size: 11px; letter-spacing: .01em; }}
.news .mkt a:hover {{ text-decoration: underline; }}
/* Justified, with hyphenation doing the work. Justification alone opens
   rivers at this column width; auto hyphens let the browser break long words
   and close the gaps, which is what keeps the right edge clean. */
.news .mkt p {{ text-align: justify !important; hyphens: auto !important; -webkit-hyphens: auto !important; font-size: 13.5px; line-height: 1.62; }}
.news .mkt {{ padding: 14px 16px; }}
.news .mkt h6 {{ letter-spacing: .09em; }}
/* Commodities blurbs run three times longer than Financials, so the two
   columns fall out of step within one screen. Cap and scroll instead. */
.news .card {{ max-height: 76vh; overflow-y: auto; }}
/* Every control label in the same register as the tabs: Inter, caps, tracked.
   Table contents are untouched — this is chrome only. */
.stButton button, .stRadio label, .sk-src {{ text-transform: uppercase !important; letter-spacing: .09em !important; }}
.stButton button {{ width: auto; min-width: 32px; height: 30px; min-height: 30px; padding: 0 13px; font-size: 10.5px; font-weight: 650; line-height: 1; border-radius: 4px; border: 1px solid {t.get('line')}; background: {t.get('surface')}; color: {t.get('mute')}; transition: color .15s, border-color .15s; }}
.stButton button p {{ font-size: 10.5px !important; font-weight: 650 !important; margin: 0 !important; }}
.stButton button:hover, .stButton button:focus {{ border-color: {t.get('teal')}; color: {t.get('teal')} !important; box-shadow: none; }}
.stButton button:hover p {{ color: {t.get('teal')} !important; }}
.stRadio label p {{ font-size: 10.5px !important; font-weight: 650 !important; letter-spacing: .09em !important; text-transform: uppercase !important; }}
/* Radio labels, the selectbox value and the digest block all set colour on
   themselves, so inheriting from body does not reach them. */
.stRadio label, .stRadio label p {{ color: {t.get('mute')} !important; }}
.stRadio [role="radio"][aria-checked="true"] + div, .stRadio [role="radio"][aria-checked="true"] + div p {{ color: {t.get('teal')} !important; }}
[data-testid="stSelectbox"] input {{ color: {t.get('ink')} !important; }}
pre, pre *, code {{ color: {t.get('ink')} !important; }}
[data-testid="stCode"], [data-testid="stCode"] pre {{ background: {t.get('surface')} !important; }}
/* The theme switch sits at the right end of the tab rule. Streamlit renders
   it as its own element, so it is anchored with an empty marker div and
   lifted into place; :has() picks the container holding the marker and the
   adjacent sibling is the button. Nudge `top` if it lands off the line. */
.block-container {{ position: relative; }}
[data-testid="stElementContainer"]:has(#sk-theme-anchor) {{ height: 0; margin: 0; }}
/* right matches .block-container's own padding-right: an absolutely positioned
   child resolves `right` against the padding box, so `right: 0` hung the switch
   24px past the end of the tab rule it is meant to sit on. */
{sw} {{ position: absolute; right: 24px; top: {SWITCH_TOP}px; z-index: 6; width: auto; }}
/* Per-tab source line: what this tab is reading, in the register of a
   footnote rather than a heading. */
.sk-src {{ font-size: 10.5px; color: {t.get('mute')}; padding: 2px 0 0; }}
/* Methodology as a definition grid rather than a paragraph. Two columns so it
   fills the width under a wide table instead of running as a narrow column of
   prose, and a fixed term column so the eye can scan down the left edge. */
.sk-defs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 34px; margin: 16px 0 0; }}
.sk-defs > div {{ display: grid; grid-template-columns: 92px 1fr; gap: 12px; padding: 7px 0; border-top: 1px solid {t.get('hair', t.get('line'))}; align-items: baseline; }}
.sk-defs b {{ font-family: var(--sans) !important; font-size: 10.5px; font-weight: 650; letter-spacing: .07em; text-transform: uppercase; color: {t.get('body')}; }}
.sk-defs span {{ font-family: var(--sans) !important; font-size: 12.5px; line-height: 1.5; color: {t.get('mute')}; }}
@media (max-width: 900px) {{ .sk-defs {{ grid-template-columns: 1fr; }} }}
/* 1.59 renders the selectbox as a react-aria ComboBox, so the old
   div[data-baseweb="select"] never matched and the control kept config.toml's
   dark secondaryBackgroundColor — which in light mode put the ink at 1.1:1 on
   its own box. Addressed through the stable testid plus the inner role=group. */
[data-testid="stSelectbox"] div[role="group"] {{ background: {t.get('surface')} !important; border-color: {t.get('line')} !important; font-size: 13px; }}
.stRadio [role="radiogroup"] {{ gap: 4px; flex-wrap: wrap; }}
/* No red on numbers, anywhere in the app. sakata.css paints .neg red for the
   static site; here every negative figure — Board changes, Tot%, roll and
   carry, vs-leg, the Sigma column — reads amber instead, so the tab uses one
   two-colour language throughout: teal is the good side, amber the other one.
   The sign character and the token still carry the direction; only the alarm
   goes. .warn is the same colour by intent: an elevated percentile and a
   negative number are both "look here", not "you lost money". */
.warn, td.neg, .neg {{ color: {t.get('amber')} !important; }}
/* Group rule inside a wide table. Margins runs twelve columns in three
   blocks and the vol grid four pairs; a hairline at each block edge does
   what a gap cannot, since a table cannot be given one without breaking the
   row borders.
   Half-opacity faint, not --line. The host stylesheet already draws every
   column boundary at white 10%, which over --surface lands brighter than
   --line does — so the block rule was the FAINTEST vertical in the table
   and the grouping it exists to show read as noise. It has to beat the
   ordinary column line to mean anything. */
th.sep, td.sep {{ border-left: 1px solid {t.get('faint')}80; }}
/* The vol grid divides four times in eight columns, twice the density of the
   margin table's three blocks, and the cells either side are already tinted —
   so the block rule there has to carry further than a hairline. Half-opacity
   mute: still a line rather than a border, but one you can find without
   looking for it. */
th.tfsep, td.tfsep {{ border-left: 1px solid {t.get('mute')}8c; }}
/* Charts keep their own up/down tokens — a candle body is a mark, not a
   number — so this deliberately does not reach inside svg. */
svg .neg {{ color: inherit !important; }}
/* Spread charts: two per row rather than three. Twelve cards three-up made each
   one too short to read the shape that justifies the row. */
.cgrid {{ grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 26px 22px !important; }}
.cgrid .plot {{ padding: 14px 14px 10px; margin: 0; }}
/* space-between alone left the label and the ER readout touching at this card
   width — they exactly fill it — so the pair read as one string. */
.cgrid .ctitle {{ margin-bottom: 2px; gap: 14px; align-items: baseline; }}
.cgrid .ctitle b {{ flex: none; }}
.cgrid .ctitle span {{ text-align: right; }}
.cgrid .clegend {{ display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px; margin-bottom: 4px; }}
/* Risk stats under the legend: one line, wrapping, so the card answers the
   same questions the table row does without leaving the picture. */
/* Seven stats, one line: ER (Adj) joined them when it left the title, and
   a wrapped eighth of a row reads as a mistake rather than as overflow.
   10.5px with an 8px gap leaves the widest card 42px of slack, which is
   the margin a three-digit Sharpe or a 100% Vol needs. */
/* A caption that introduces a table belongs to the table's width, not to
   the 74ch measure that keeps body prose readable. */
.note.wide {{ max-width: none; font-size: 12.5px; line-height: 1.6; }}
.cstats {{ display: flex; flex-wrap: wrap; gap: 3px 8px; margin: 0 0 8px; font-size: 10.5px; line-height: 1.5; }}
/* Portfolio: the score and its curve share the top band, the weights run the
   width of the page underneath. Squeezing eleven weight columns in beside the
   chart cost them the cell padding and two points of type; the conclusion is
   four rows of seven numbers and one line, and that is what fits in halves.
   The split is whatever stops the eight-column table scrolling — 496px at the
   1160px measure — and the chart takes the rest, being a shape rather than a
   column count. Each card keeps its own scroll, so a narrow laptop gets a
   cramped card rather than a broken page. */
.pfgrid {{ display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, 1.3fr); gap: 18px; align-items: start; margin-bottom: 4px; }}
@media (max-width: 1000px) {{ .pfgrid {{ grid-template-columns: 1fr; }} }}
.pfgrid .plot {{ padding: 13px 12px 10px; margin: 0; }}
.pfgrid .plot .scroll {{ margin-bottom: 4px; }}
/* Half a page is not the full width the table cells were sized for, but it is
   no longer the 400px that had the headers down at 9px either. */
.pfgrid table {{ font-size: 12.5px; }}
.pfgrid td {{ padding: 6px; }}
.pfgrid thead th {{ padding: 6px; font-size: 9.5px; letter-spacing: .04em; }}
@media (max-width: 900px) {{ .cgrid {{ grid-template-columns: 1fr !important; }} }}
/* Icon button: square, quiet, teal on hover — the header switch from
   index.html, minus the SVG. Scoped to the theme toggle. Unscoped, this block
   sat after the text-button rule and won, so `width: 32px; padding: 0` also
   hit Refresh and broke the word onto two lines. */
{sw} .stButton button {{ width: 32px; padding: 0; font-size: 14px; }}
{sw} .stButton button p {{ font-size: 14px !important; }}
.sk-head {{ display: flex; align-items: center; gap: 10px; margin: 0 0 4px; }}
.sk-mark {{ flex: none; color: {t.get('teal')}; margin-bottom: 2px; }}
.sk-word {{ font-family: var(--display); font-size: 23px; font-weight: 800; letter-spacing: -.035em; color: {t.get('ink')}; margin: 0; line-height: 1; }}
.sk-rule {{ flex: 1; height: 1px; background: {t.get('line')}; margin: 2px 4px 0; }}
.sk-stamp {{ font-size: 11px; color: {t.get('faint')}; white-space: nowrap; letter-spacing: -.02em; }}
.chart {{ width: 100%; height: auto; }}
"""


MARK = ('<svg class="sk-mark" width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">'
        '<path d="M22.3 7.8L22.8 8.0L23.3 8.3L23.8 8.6L24.2 9.0L24.5 9.4L24.8 9.9L25.0 10.4L25.2 10.9L25.4 11.3L25.6 11.8L25.7 12.3L25.8 12.8L25.9 13.3L25.9 13.8L26.0 14.2L26.0 14.7L26.0 15.2L26.0 15.7L26.0 16.2L25.9 16.7L25.8 17.2L25.7 17.6L25.5 18.1L25.3 18.6L25.1 19.0L24.8 19.5L24.5 20.0L24.2 20.4L23.9 20.8L23.6 21.2L23.2 21.6L22.9 22.0L22.5 22.4L22.1 22.8L21.6 23.1L21.2 23.4L20.7 23.8L20.2 24.0L19.7 24.3L19.2 24.5L18.7 24.8L18.1 24.9L17.6 25.1L17.0 25.3L16.5 25.4L15.9 25.4L15.3 25.5L14.8 25.5L14.2 25.5L13.6 25.5L13.1 25.4L12.5 25.3L11.9 25.2L11.4 25.1L10.9 24.9L10.3 24.7L9.8 24.4L9.3 24.2L8.8 23.9L8.4 23.6L8.0 23.2L7.6 22.7L7.2 22.3L6.9 21.9L6.6 21.4L6.3 21.0L6.1 20.5L5.9 20.0L5.7 19.5L5.5 19.0L5.3 18.4L5.2 17.9L5.2 17.4L5.1 16.9L5.1 16.3L5.1 15.8L5.2 15.2L5.2 14.7L5.4 14.2L5.5 13.6L5.7 13.1L5.9 12.6L6.1 12.1L6.4 11.6L6.7 11.1L7.1 10.6L7.5 10.2L7.9 9.7L8.3 9.3L8.7 8.9L9.2 8.6L9.7 8.2L10.2 7.9L10.8 7.6L11.3 7.3L11.9 7.1L12.4 6.9L13.0 6.7L13.6 6.5L14.2 6.4L14.7 6.3L15.3 6.2L15.9 6.1L16.5 6.1L17.1 6.1L17.7 6.1L18.3 6.1L18.9 6.2L19.5 6.3L20.1 6.4L20.1 6.4L20.2 6.4L20.2 6.4L20.2 6.3L20.3 6.3L20.3 6.3L20.3 6.2L20.3 6.2L20.3 6.1L20.3 6.1L20.3 6.1L20.3 6.0L20.2 6.0L20.2 6.0L19.6 5.8L19.0 5.7L18.4 5.6L17.8 5.5L17.2 5.4L16.5 5.4L15.9 5.4L15.3 5.4L14.6 5.4L14.0 5.5L13.4 5.6L12.7 5.7L12.1 5.9L11.5 6.0L10.9 6.3L10.2 6.5L9.6 6.8L9.0 7.1L8.4 7.4L7.9 7.8L7.3 8.2L6.8 8.6L6.3 9.1L5.8 9.6L5.4 10.1L5.0 10.7L4.6 11.2L4.3 11.8L4.0 12.5L3.8 13.1L3.6 13.8L3.5 14.4L3.4 15.1L3.4 15.7L3.4 16.4L3.5 17.0L3.6 17.7L3.7 18.3L3.9 18.9L4.1 19.5L4.4 20.0L4.7 20.6L5.0 21.1L5.3 21.6L5.7 22.1L6.1 22.5L6.5 23.0L7.0 23.4L7.4 23.8L7.9 24.1L8.4 24.5L8.8 24.9L9.3 25.3L9.8 25.6L10.4 25.9L10.9 26.2L11.5 26.5L12.1 26.8L12.7 27.0L13.3 27.2L14.0 27.3L14.6 27.5L15.3 27.6L16.0 27.6L16.7 27.6L17.3 27.6L18.0 27.5L18.7 27.4L19.4 27.3L20.1 27.1L20.8 26.9L21.5 26.7L22.1 26.4L22.7 26.1L23.4 25.7L24.0 25.3L24.5 24.9L25.1 24.4L25.6 24.0L26.1 23.5L26.6 22.9L27.0 22.4L27.4 21.8L27.8 21.2L28.1 20.6L28.4 19.9L28.6 19.3L28.8 18.6L29.0 18.0L29.1 17.3L29.3 16.6L29.4 15.9L29.4 15.2L29.4 14.5L29.3 13.8L29.1 13.1L28.9 12.4L28.7 11.8L28.4 11.2L28.0 10.6L27.6 10.1L27.1 9.6L26.6 9.1L26.1 8.7L25.6 8.3L25.0 7.9L24.5 7.6L24.0 7.2L23.5 6.8L23.0 6.4L22.8 6.4L22.6 6.3L22.5 6.4L22.3 6.4L22.2 6.5L22.0 6.6L21.9 6.8L21.9 6.9L21.8 7.1L21.9 7.3L21.9 7.4L22.0 7.6L22.1 7.7Z" fill="currentColor"/>'
        '<path d="M4.1 17.8L4.0 15.9L4.2 14.0L4.8 12.1L5.9 10.4L7.2 8.9L8.9 7.7L10.7 6.8L12.5 6.1L14.5 5.7L16.4 5.6L18.3 5.7L20.2 6.0" fill="none" stroke="currentColor" stroke-width="0.3" stroke-linecap="round" opacity="0.55"/>'
        '<path d="M7.5 23.2L6.0 21.4L4.9 19.4L4.3 17.1L4.4 14.7L5.1 12.4L6.4 10.2L8.2 8.4L10.4 7.1L12.8 6.2L15.3 5.8L17.7 5.8L20.1 6.2" fill="none" stroke="currentColor" stroke-width="0.26" stroke-linecap="round" opacity="0.5"/>'
        '<path d="M5.2 12.7L5.9 11.4L6.7 10.2L7.8 9.1L8.9 8.2L10.2 7.4L11.6 6.8L13.0 6.4L14.4 6.1L15.8 5.9L17.3 5.9L18.7 6.1L20.1 6.4" fill="none" stroke="currentColor" stroke-width="0.22" stroke-linecap="round" opacity="0.45"/>'
        '<circle cx="11.6" cy="19.0" r="2.2" fill="#d3a355"/>'
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
    """The lockup: mark, wordmark, stamp. No rule — the tab strip already
    draws a line two rows down, and two horizontal rules that close together
    read as a mistake rather than as structure.

    Everything here is an inline style on a span. Streamlit's own rules for
    <h1> and for its markdown container are specific enough to win against a
    class, which is what pushed the mark onto its own line and stripped the
    teal off it.
    """
    t = tokens(st.session_state.get("dark", True))
    md(f'<div style="display:flex;align-items:baseline;gap:11px;margin:0 0 2px">'
       f'<span style="flex:none;line-height:0;color:{t.get("teal")};'
       f'align-self:center">{MARK}</span>'
       f'<span style="font-family:var(--display),Inter,sans-serif;font-size:27px;'
       f'font-weight:800;letter-spacing:-.035em;color:{t.get("ink")};'
       f'line-height:1">Sakata</span>'
       f'<span style="flex:1"></span>'
       f'<span style="font-size:11px;color:{t.get("faint")};white-space:nowrap;'
       f'letter-spacing:.01em">{esc(stamp)}</span></div>')


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


def table(head: str, body: str, cols: str = "") -> str:
    """`cols` is an optional <colgroup>. Passing one also switches the table to
    a fixed layout, which is the only way two stacked tables can be made to
    share a column grid — auto layout sizes each table independently from its
    own content, so the Spreads blocks drifted out of line with each other."""
    fixed = ' style="table-layout:fixed"' if cols else ""
    group = f"<colgroup>{cols}</colgroup>" if cols else ""
    return (f'<div class="card scroll"><table{fixed}>{group}'
            f"<thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def swatch(sec: str) -> str:
    return f'<i class="sw" style="background:{SECTOR_COL.get(sec, C["other"])}"></i>'


def eyebrow(text: str, extra: str = "") -> str:
    return f'<div class="eyebrow">{esc(text)}{extra}</div>'


def note(html_text: str, wide: bool = False) -> str:
    """`wide` drops the 74ch measure so the text runs the width of the
    table it introduces. Prose wants a short line; a caption under a
    900px table wants to be one or two lines rather than five."""
    return f'<div class="note{" wide" if wide else ""}">{html_text}</div>'


def chips(items) -> str:
    return ('<div class="chips">' +
            "".join(f'<span class="chip">{esc(c)}</span>' for c in items) +
            "</div>")
