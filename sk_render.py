"""Sakata — the eight tabs, ported from site/js/*.js.

Each function takes the computed data and returns HTML. The markup is the
same markup the static site emits, so sakata.css styles it without a single
new rule. Interactive state (selected horizon, window, instrument) comes from
Streamlit widgets rather than click handlers, which is the only structural
difference from the browser version.

Events keeps its calendar rules rather than being precomputed, for the same
reason it was never built into JSON: roll dates and expiries follow fixed
rules, so evaluating them at render time keeps them correct regardless of how
old the price data is.
"""
import datetime as dt
import os

import sk_charts as CH
import sk_knowledge as KN
import sk_margins as MG
import sk_spreads as SP
import sk_universe as U
from sk_ui import (BIAS_COL, C, SECTOR_COL, cell, chips, esc, eyebrow, note,
                   num, pct, swatch, table)

HZ = ["Day", "WTD", "MTD", "QTD", "YTD"]


def _tok() -> dict:
    """Live tokens for the few places that need an inline style."""
    from sk_ui import tokens
    import streamlit as st
    return tokens(st.session_state.get("dark", True))


# ------------------------------------------------------------------ Board
def board(d: dict, hz: str = "Day") -> str:
    by_sec = {}
    for r in d["rows"]:
        by_sec.setdefault(r["sector"], []).append(r)

    agg = []
    for s, rows in by_sec.items():
        vs = [r[hz] for r in rows if r.get(hz) is not None]
        agg.append({"k": s, "c": SECTOR_COL.get(s, C["other"]),
                    "v": sum(vs) / len(vs) if vs else 0.0})
    agg.sort(key=lambda a: -a["v"])

    def panel(group):
        body, legend = "", ""
        for sec in U.GROUPS.get(group, []):
            rows = by_sec.get(sec)
            if not rows:
                continue
            legend += f'<span class="key">{swatch(sec)}{esc(sec)}</span>'
            for r in rows:
                body += (f'<tr><td class="l">{swatch(sec)}{esc(r["code"])} '
                         f'<span class="nm">{esc(r["name"])}</span></td>'
                         f'<td class="last">'
                         f'{num(r["last"], r["dec"]) or "—"}</td>')
                for h in HZ:
                    v = r.get(h)
                    if v is None:
                        body += '<td class="faint">—</td>'
                        continue
                    cls = "pos" if v >= 0 else "neg"
                    if h == hz:
                        cls += " on"
                    body += (f'<td class="{cls}">{"+" if v >= 0 else ""}'
                             f'{num(v, 2)}</td>')
                body += "</tr>"
        head = ('<th class="l">Instrument</th><th>Last</th>' +
                "".join(f'<th{" class=\"on\"" if h == hz else ""}>{h}</th>'
                        for h in HZ))
        return (f'<div>{eyebrow(group, f"<span class=\'legend\'>{legend}</span>")}'
                f"{table(head, body)}</div>")

    return (eyebrow(f"Sector performance · {hz} %")
            + f'<div class="plot">{CH.bar_chart(agg)}</div>'
            + '<div class="grid2" style="margin-top:16px">'
            + panel("Financials") + panel("Commodities") + "</div>")


# -------------------------------------------------------------- Technical
# The mark says WHERE, the number says HOW MANY AGREE. A summed score can
# only ever be the second: +1 through the prior high and +1 drifting the
# middle of it are the same digit and not the same market. So the glyph
# leads and carries position, and it is a grammar rather than seven
# arbitrary symbols — which is what lets it be read without the legend
# after the first day:
#
#   size   how far out     large = past the prior range's edge
#                          small = past the retrace bands, still inside
#   fill   did it hold     solid = price is still there
#                          hollow = it went and came back
#   none   nothing to say  between the bands, the middle of the range
#
# Mid is blank rather than a dot. Drawn as "·" it was a speck at 13px
# sitting beside "▴" and "▾", which are also specks, and the one
# discrimination the eye cannot make in a dense grid is small-mark against
# other-small-mark. Absence against presence is the easiest it can make. The
# middle of a range is also the cell with the least to say, so spending the
# most delicate mark on it had it backwards twice.
#
# Failure needed the hollow pair because it has nowhere else to live. It is
# not a fourth vote and it does not move the score — a break that was given
# back SHOULD score as Range — so until now it was invisible in a cell and
# recoverable only by opening a chart.
STRUCT_MARK = {
    "Breakout": "▲", "Failed breakout": "△", "Above bands": "▴",
    "Mid": "",
    "Below bands": "▾", "Failed breakdown": "▽", "Breakdown": "▼",
}
# Sorting still counts only the breaks that held. A column that poked and
# gave it back has not earned the top of the table.
BREAK_VOTE = {"Breakout": 1, "Breakdown": -1}

# A legend is a lookup, not a paragraph. Written as prose it ran four lines
# under the table and had to be re-parsed every time, because a sentence is
# read start to finish while a key is read by finding the one row you want.
MARK_KEYS = (
    ("▲", "Holding breakout", 1), ("△", "Failed breakout", 1),
    ("▴", "Above retrace", 1), ("", "Mid", 0),
    ("▾", "Below retrace", -1), ("▽", "Failed breakdown", -1),
    ("▼", "Holding breakdown", -1),
)
# The band mark trails the score, smaller, in the chart's own colours for the
# two levels: orange for the sell band, cyan for the buy band. The arrow is
# the REACTION rather than the position — down out of the sell band, up off
# the buy band — so colour and direction agree, and the mark needs no
# reconciling with the score sitting beside it.
#
# It marks only the give-back. An arrow for "currently beyond the band" was
# drawn first and was pure duplication: the glyph three characters to the
# left already says that. Between the duplication and rb crossing rs it put
# a mark on nine cells in ten.
BAND_MARK = {"rejected": "\u2193", "reclaimed": "\u2191"}

def _band_marks(c: dict) -> str:
    """RS then RB, each in its own colour, or nothing when neither is live."""
    out = ""
    for key, col in (("rsMark", C["amber"]), ("rbMark", C["teal"])):
        m = c.get(key)
        if m:
            out += (f'<span style="color:{col};font-size:11px;'
                    f'font-weight:700">{BAND_MARK[m]}</span>')
    return f'<span style="margin-left:5px">{out}</span>' if out else ""


def _mark_legend() -> str:
    items = ""
    for glyph, label, side in MARK_KEYS:
        col = BIAS_COL["3"] if side > 0 else (
            BIAS_COL["-3"] if side < 0 else C["faint"])
        mark = (f'<span style="color:{col};font-weight:700">{glyph}</span>'
                if glyph else f'<span style="color:{C["faint"]}">–</span>')
        items += f'<span class="key">{mark}&nbsp;&nbsp;{esc(label)}</span>'
    for key, col, label in (
            ("rejected", C["amber"], "Rejected at sell band"),
            ("reclaimed", C["teal"], "Reclaimed buy band")):
        items += (f'<span class="key"><span style="color:{col};'
                  f'font-weight:700">{BAND_MARK[key]}</span>'
                  f'&nbsp;&nbsp;{esc(label)}</span>')
    return ('<div class="legend" style="margin:12px 0 0;gap:12px 18px">'
            f'{items}</div>')


def _break_line(label, items, colour, faint) -> str:
    """One row of chips: what is through its edge, furthest through first."""
    if not items:
        return ""
    body = "".join(
        f'<span class="chip" style="color:{colour}">{esc(k)} '
        f'{"—" if p is None else num(p, 0) + "%"}</span>'
        for k, p in items)
    return (f'<div class="chips"><span style="margin-right:10px;'
            f'font-family:var(--sans);font-size:10.5px;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:.08em;color:{faint}">'
            f'{esc(label)}</span>{body}</div>')


def technical_matrix(d: dict, code: str, hz: str) -> str:
    """The survey half: what is breaking, and the whole ladder."""
    order, grid = d["order"], d["grid"]

    # Breaking now, before anything else. The tab's first question is "what is
    # outside its range", and the matrix answered it only to a reader willing
    # to decode a signed number in ninety-five cells. Position rides with the
    # code because 101% and 140% of the prior range are not the same break.
    out_up, out_dn = [], []
    for u_code in U.CODES:
        c = grid.get(u_code, {}).get(hz)
        if not c:
            continue
        if c["regime"] == "Breakout":
            out_up.append((u_code, c.get("pos")))
        elif c["regime"] == "Breakdown":
            out_dn.append((u_code, c.get("pos")))
    out_up.sort(key=lambda x: -(x[1] if x[1] is not None else 0))
    out_dn.sort(key=lambda x: (x[1] if x[1] is not None else 0))

    if out_up or out_dn:
        strip = (_break_line("Above prior high", out_up, C["teal"], C["faint"])
                 + _break_line("Below prior low", out_dn, C["amber"],
                               C["faint"]))
    else:
        strip = note(f"Nothing is outside its prior <b>{esc(hz)}</b> range — "
                     "every instrument on the ladder is trading between the "
                     "high and the low it made last period.")

    # Instruments across the top, the ladder down the side. A column is now
    # one instrument read top to bottom, which is the shape the question has:
    # "is this thing broken on more than one rung" is a glance down a column,
    # where before it was a scan across a row of five while nineteen other
    # rows pulled the eye sideways. Nineteen short codes fit a header; the
    # names did not, and they were the widest thing in the old table.
    legend, seen = "", []
    for u_code in U.CODES:
        sec = U.SECTOR[u_code]
        if grid.get(u_code) and sec not in seen:
            seen.append(sec)
            legend += f'<span class="key">{swatch(sec)}{esc(sec)}</span>'

    cols = []
    for u_code in U.CODES:
        g = grid.get(u_code)
        if not g:
            continue
        tot = sum(c["score"] for c in g.values())
        breaks = sum(BREAK_VOTE.get(c["regime"], 0) for c in g.values())
        cols.append({"code": u_code, "by_h": g, "tot": tot, "breaks": breaks})

    # Breakout first, literally: the net break count across the ladder orders
    # the columns left to right, the bias total settles ties, and the universe
    # order settles the rest so a quiet day still renders in a stable order.
    rank = {c: i for i, c in enumerate(U.CODES)}
    cols.sort(key=lambda s: (-s["breaks"], -s["tot"], rank[s["code"]]))

    # The instrument the dropdown chose takes a raised column, the horizon it
    # chose a raised row, and the cell where they cross goes one tone darker.
    # Two selectors sit above this table and neither of them used to be
    # visible in it: the reader picked a pair and then hunted for the cell.
    # Nineteen columns overran a 1280px window by 73px, which clipped ZB and
    # ZN — the two most broken-down instruments on the board, and the last
    # thing a wide table should hide. Four pixels off each side of every cell
    # buys 152px and costs nothing a reader can see.
    TIGHT = "padding-left:8px;padding-right:8px;"
    head = ('<th class="l">Horizon</th>'
            + "".join(
                f'<th{" class=\"on\"" if s["code"] == code else ""}'
                f' style="{TIGHT}" title="{esc(U.NAME[s["code"]])}">'
                f'{swatch(U.SECTOR[s["code"]])}{esc(s["code"])}</th>'
                for s in cols))

    body = ""
    for h in order:
        on = h == hz
        cells = ""
        for s in cols:
            sel = s["code"] == code
            bg = TIGHT + ("background:var(--hair);" if sel and on
                          else "background:var(--raised);"
                          if sel else "")
            c = s["by_h"].get(h)
            if not c:
                cells += f'<td class="faint" style="{bg}">\u2014</td>'
                continue
            # structure, not regime: a failure had no way to reach the
            # reader before, and now it is named in the mark and again
            # in the tooltip that explains the mark.
            struct = c.get("structure", c["regime"])
            note_ = c.get("bandNote")
            title = (f'{s["code"]} {U.NAME[s["code"]]} · {h} · '
                     f'{c["bias"]} · {struct} · {c["regime"]} / '
                     f'{c["retrace"]} / {c["trend"]}'
                     + (f' · {note_}' if note_ else ""))
            cells += (f'<td style="{bg}color:{BIAS_COL[str(c["score"])]};'
                      f'font-weight:{700 if on or sel else 600}" '
                      f'title="{esc(title)}">{STRUCT_MARK.get(struct, "")}'
                      f'{"+" if c["score"] > 0 else ""}{c["score"]}'
                      f'{_band_marks(c)}</td>')
        body += (f'<tr{" class=\"out\"" if on else ""}>'
                 f'<td class="l">{esc(h)}</td>{cells}</tr>')

    tot_cells = ""
    for s in cols:
        sel = s["code"] == code
        bg = TIGHT + ("background:var(--raised);" if sel else "")
        # The footing takes the ends of the ladder, not the middle of it: a
        # short column should close as loudly as a long one does, and base
        # amber against a bright green did not.
        tot_cells += (f'<td style="{bg}color:'
                      f'{C["pos"] if s["tot"] >= 0 else BIAS_COL["-3"]};'
                      f'font-weight:700">{"+" if s["tot"] > 0 else ""}'
                      f'{s["tot"]}</td>')
    body += ('<tr><td class="l" title="Ladder total: every horizon\u2019s bias '
             'for this instrument, added up, so a column that agrees with '
             'itself reads far from zero.">\u03a3</td>'
             f'{tot_cells}</tr>')

    return (eyebrow(f"Breaking now · {hz}")
            + strip
            + eyebrow("Bias matrix", f'<span class="legend">{legend}</span>')
            + table(head, body)
            # The explainer sits UNDER the table it explains. Four lines of
            # prose above the matrix pushed the one thing worth seeing first
            # down the page, and a legend is read once and then never again.
            + _mark_legend()
            + note("Large is the prior range’s edge, small the retrace "
                   "band, hollow means it went and came back. The number is "
                   "the bias: <b>range</b>, <b>retrace</b> and <b>trend</b>, "
                   "one vote each, summed −3 to +3. Columns run "
                   "most-broken first; Σ totals the ladder.", wide=True))


def _range_table(g: dict, order: list, hz: str, dec: int) -> str:
    """Prior range, its average, its rank and the vol, for every rung."""
    rows = ""
    for h in order:
        c = g.get(h)
        if not c or c.get("segRange") is None:
            continue
        pctile = c.get("segRangePct")
        tone = (BIAS_COL["-3"] if (pctile or 0) >= 80
                else C["faint"] if (pctile or 0) <= 20 else None)
        cells = (cell(c.get("segRange"), dec) + cell(c.get("segAtr"), dec)
                 + (f'<td>{num(c["segRangeX"], 2)}\u00d7</td>'
                    if c.get("segRangeX") is not None
                    else '<td class="faint">\u2014</td>')
                 + (f'<td style="color:{tone}">{num(pctile, 0)}</td>'
                    if tone else cell(pctile, 0))
                 + cell(c.get("segHv"), 1))
        rows += (f'<tr{" class=\"out\"" if h == hz else ""}>'
                 f'<td class="l">{esc(h)}</td>{cells}</tr>')
    if not rows:
        return ""
    head = ('<th class="l">Horizon</th>'
            '<th title="High minus low of the last completed segment.">'
            'Prior range</th>'
            '<th title="Mean range of the last 20 completed segments.">'
            'ATR 20</th>'
            '<th title="The prior range over that average. Above 1 is a wider '
            'period than usual, below 1 a quieter one.">\u00d7 ATR</th>'
            '<th title="Where the prior range sits among the last 52 '
            'completed segments.">Pctile</th>'
            '<th title="Annualised volatility of segment-to-segment closes '
            'over the last 20 segments. A year cannot be annualised from one '
            'observation, so the Year rung is blank.">HV %</th>')
    return eyebrow("Range and volatility") + table(head, rows)


def technical_levels(d: dict, code: str, hz: str, dec: int) -> str:
    """The drill-down half: the pair the selectors chose, and its levels.

    Split from the matrix so the two selectors can sit between them. They
    steer this half and only highlight the other, so above both they read as
    controls on the whole tab; here they read as what they are, and the
    matrix gets the top of the page.
    """
    grid = d["grid"]
    c = grid.get(code, {}).get(hz, {})
    lv = "".join(
        f'<tr><td class="l">{k}</td>{cell(v, dec)}</tr>' for k, v in [
            ("Prior high", c.get("high")), ("RS target", c.get("rs")),
            ("Mid", c.get("mid")), ("RB stop", c.get("rb")),
            ("Prior low", c.get("low")), ("Close", c.get("close")),
            ("MA100", c.get("ma100")), ("MA200", c.get("ma200"))])

    # One row per rung rather than chips for the selected one. The chips
    # answered "how wide was the prior period" for a single horizon, and the
    # question is comparative — a week at the 25th percentile means something
    # different when the day inside it is at the 69th. The Levels table keeps
    # holding prices only; a percentile, a multiple and a vol are not prices,
    # and sharing that column with them makes every number in it need reading
    # twice to know what it is.
    vol = _range_table(d["grid"].get(code, {}), d["order"], hz, dec)

    dash = "—"
    pos = dash if c.get("pos") is None else f'{num(c["pos"], 0)}%'
    rr = dash if c.get("rr_retrace") is None else num(c["rr_retrace"], 2)
    struct = c.get("structure", c.get("regime", dash))
    return (note(f'<b>{esc(code)} · {esc(hz)}</b> — '
                 f'{STRUCT_MARK.get(struct, "")} {esc(struct)} · '
                 f'{esc(c.get("bias", dash))} ({esc(c.get("regime", dash))}'
                 f' / {esc(c.get("retrace", dash))}'
                 f' / {esc(c.get("trend", dash))}) · position {pos} of '
                 f'prior range · R:R to band {rr}'
                 + (f' · <b>{esc(c["bandNote"])}</b>'
                    if c.get("bandNote") else ""))
            + vol
            + eyebrow("Levels")
            + table('<th class="l">Level</th><th>Price</th>', lv))


# ---------------------------------------------------------------- Spreads
# Default is the normalised measure. Within one window ER and ER (Adj) order
# rows identically — bars is constant, so sqrt(bars) is a positive scale factor
# — but the adjusted one is what the by-window tables compare, and offering two
# keys that behave the same inside a table only invites the question.
# ROA first, which makes it the default selection: return per unit of the
# worst hole is the question a spread is usually being asked, and ER (Adj)
# answers a narrower one — how straight the path was, whatever it paid.
SORTS = {"ROA": "roa", "ER (Adj)": "erAdj", "Win%": "win", "Tot%": "tot",
         "Sharpe": "sharpe"}
DEFAULT_SORT = next(iter(SORTS))

# Card stats carry short labels; this is which one each ranking lights up.
RANKED_AS = {"erAdj": "ER (Adj)", "win": "Win%", "tot": "Tot%",
             "sharpe": "Sharpe", "roa": "ROA"}

# Leg weighting. This is not a display switch: it selects the return series the
# whole field is computed from, so ER, Sharpe, drawdown, the ranking and the
# chart's spread line all follow it. Vol equalises dollar RISK, notional
# equalises dollar EXPOSURE. The Size column shows the matching contract ratio.
# One table, not four. Each weighting knows its internal name (what
# weighted_spread calls it), the label a reader picked, and which pair of row
# keys carries its contract ratio — those three were drifting apart across
# BASES / SIZINGS / _SIZE_KEYS / _SIZE_LABEL, which is how the column header
# ended up printing "equal" at a reader who had chosen "Notional".
WEIGHTINGS = {
    "vol":   {"label": "vol",      "keys": ("sizeVol", "sizeVolExact")},
    "equal": {"label": "notional", "keys": ("sizeNot", "sizeNotExact")},
}
# One selector, one meaning: it decides the weighting the field is computed on
# AND the contract ratio shown against it. There used to be a second,
# display-only control with a "Match basis" option that deferred to this one —
# two knobs for a distinction that needed explaining every time it was seen.
BASES = {"Vol": "vol", "Notional": "equal"}


def _wincols(n_windows: int) -> str:
    """One column grid shared by the two by-window blocks, so their windows sit
    on the same verticals. Both tables must therefore carry the SAME number of
    columns — which is why the outrights matrix now renders every display
    window, dashing the ones with no data rather than dropping the column."""
    return '<col style="width:21%">' + "<col>" * n_windows


def _pos_label(r: dict) -> str:
    lg, sh = r.get("long"), r.get("short")
    if lg and sh:
        return f"{lg}/{sh}"
    return f"long {lg}" if lg else (f"short {sh}" if sh else "—")


def _optimal(d: dict, per: str, t: dict, sort: str = DEFAULT_SORT) -> str:
    """Best spread in each window — windows across the top, metrics down the
    left, matching the outrights matrix directly beneath it.

    Transposed for that reason alone: the two blocks answer the same question
    at different grains, so reading one after the other should not mean
    re-learning which axis is which. The five windows stay in a FIXED column
    order whether or not each built, so the shape survives a reload.
    """
    wins = d.get("displayPeriods", d.get("periods", []))
    # Best BY THE CHOSEN RANKING, not by the field's own order. The summary's
    # top row is whatever ER put first, which stopped being "optimal" the
    # moment the tab could be ranked on something else.
    key = SORTS.get(sort, SORTS[DEFAULT_SORT])
    by_win = {}
    for w in wins:
        rows = (d.get("data", {}).get(w) or {}).get("rows") or []
        if not rows:
            continue
        best = max(rows, key=lambda r: (r.get(key) is not None,
                                        r.get(key) if r.get(key) is not None
                                        else 0))
        by_win[w] = dict(best, label=_pos_label(best),
                         bars=d["data"][w].get("bars"),
                         thin=d["data"][w].get("thin"))
    wash = f'background:{t.get("teal", "#0d8f83")}1a'
    ink = t.get("ink", "#0d1418")

    head = ('<th class="l"></th>'
            + "".join(f'<th{" class=\"on\"" if w == per else ""}>{esc(w)}</th>'
                      for w in wins))

    def row(label, fn, cls=""):
        cells = ""
        for w in wins:
            r = by_win.get(w)
            inner = "—" if r is None else fn(r)
            style = wash if w == per else ""
            c = f' class="{cls}"' if cls else ""
            cells += f'<td{c} style="{style}">{inner}</td>'
        return f'<tr><td class="l">{esc(label)}</td>{cells}</tr>'

    def signed(v):
        if v is None:
            return "—"
        col = t.get("pos", "#0a7c66") if v >= 0 else t.get("amber", "#96701c")
        return (f'<span style="color:{col}">{"+" if v >= 0 else ""}'
                f'{num(v, 1)}</span>')

    def bars(r):
        # A short window still ranks; the count carries the warning.
        v = r.get("bars")
        if v is None:
            return "—"
        col = t.get("amber", "#96701c") if r.get("thin") else t.get("faint")
        return f'<span style="color:{col}">{v}</span>'

    body = (
        # Right-aligned like the numbers beneath it. Left-aligning this one row
        # put a ragged cell at the top of every otherwise clean column.
        row("Best spread",
            lambda r: f'<span style="color:{ink};font-weight:600">'
                      f'{esc(r.get("label") or "—")}</span>')
        + row("ER (Adj)",
              lambda r: (f'<span style="color:{ink};font-weight:600">'
                         f'{num(r.get("erAdj"), 2)}</span>'
                         if r.get("erAdj") is not None else "—"))
        + row("ROA",
              lambda r: (f'<span style="color:{ink};font-weight:600">'
                         f'{num(r.get("roa"), 1)}</span>'
                         if r.get("roa") is not None else "—"))
        + row("Tot%", lambda r: signed(r.get("tot")))
        + row("Bars", bars))

    return (eyebrow(f"Optimal Spread by Time Window — best on {esc(sort)}")
            + table(head, body, _wincols(len(wins))))


def _outrights(d: dict, per: str, t: dict, sort: str = DEFAULT_SORT) -> str:
    """ER for every instrument held alone, every window a column.

    Rows sort on the SELECTED window, so the picker at the top of the tab
    reorders this table too — pick YTD and the year's cleanest trends rise to
    the top. Thin windows keep their column: the field ranking needs 20 bars
    before it means anything, but a single instrument's efficiency ratio is
    still a fact about the window, and leaving the column out just looked like
    a bug.
    """
    # Every display window, present or not — a dropped column would knock this
    # table out of alignment with the one above it.
    wins = list(d.get("displayPeriods", []))
    # ROA when the field is ranked on ROA, ER (Adj) otherwise. The matrix is
    # here to answer "what would holding one of these alone have done", and
    # that only helps if it answers it in the same currency the table above is
    # being read in. The other three rankings have no per-instrument column of
    # their own, so they keep the efficiency reading.
    on_roa = SORTS.get(sort) == "roa"
    src_key, metric, dp = (("outRoa", "ROA", 1) if on_roa
                           else ("outSigned", "ER (Adj)", 2))
    live = [w for w in wins if w in d.get("data", {})
            and d["data"][w].get(src_key)]
    if not wins:
        return ""
    # ER (Adj), not raw ER. This matrix compares ACROSS windows by
    # construction — the columns are the windows — which is the one place raw
    # ER cannot be read straight: it decays as 1/sqrt(n), so a 64-bar Intraday
    # column would always tower over a 229-bar YTD one for no reason but its
    # length. Multiplying by sqrt(bars) removes exactly that, and puts 1.0 at
    # the noise floor in every column.
    # SIGNED ER, adjusted: sign carries direction, so a clean downtrend reads
    # negative rather than being silently flipped into a positive "short".
    # This is both what is displayed and what the rows sort on.
    #
    # ROA needs no such correction: it is a ratio of two window-length
    # quantities, so it does not decay with the bar count the way raw ER does.
    mats = {}
    for w in live:
        src = d["data"][w].get(src_key) or {}
        if on_roa:
            mats[w] = dict(src)
        else:
            root = max(d["data"][w].get("bars", 0), 1) ** 0.5
            mats[w] = {k: (None if v is None else round(v * root, 2))
                       for k, v in src.items()}
    codes = [c for c in U.CODES if any(c in mats.get(w, {}) for w in live)]
    if not codes:
        return ""

    if not live:
        return ""
    # Sort on the number the column actually shows. Ranking on the hidden
    # Sharpe-oriented figure kept the row order stable when the display went
    # signed, but the visible effect was a column that looked unsorted: copper
    # at +0.48 sat below wheat at +0.04, because the key behind it read -0.52.
    # Longs descend from the top, shorts ascend from the bottom, and the
    # strongest conviction on either side is at one end or the other.
    skey = per if per in mats else live[0]
    codes.sort(key=lambda c: (mats[skey].get(c) is None,
                              -(mats[skey].get(c) or 0)))

    vals = [abs(v) for w in live for v in mats[w].values() if v is not None]
    ref = max(vals) if vals else 1
    ink = t.get("ink", "#0d1418")
    teal = t.get("teal", "#0d8f83")

    head = ('<th class="l">Instrument</th>'
            + "".join(f'<th{" class=\"on\"" if w == skey else ""}>{esc(w)}'
                      f'</th>' for w in wins))
    # One washed column, not ninety-five tinted cells. The old per-cell gradient
    # competed with the numbers it was meant to rank; a single wash on the
    # column the rows are sorted by says "you are here" and nothing else, and
    # matches how the by-window block above marks the same thing.
    wash = f'background:{teal}1a'
    body = ""
    for c in codes:
        cells = ""
        for w in wins:
            v = mats.get(w, {}).get(c)
            style = wash if w == skey else ""
            if v is None:
                cells += f'<td class="faint" style="{style}">—</td>'
                continue
            cells += (f'<td style="{style}">'
                      f'<span style="color:{ink};font-weight:600">'
                      f'{v:.{dp}f}</span></td>')
        body += (f'<tr><td class="l">{swatch(U.SECTOR[c])}{esc(c)} '
                 f'<span class="nm">{esc(U.NAME[c])}</span></td>{cells}</tr>')
    return (eyebrow(f"Outrights by Time Window — {esc(metric)}, ranked on "
                    f"{esc(skey)}")
            + table(head, body, _wincols(len(wins))))


# ------------------------------------------------------------- Portfolio
def portfolio(res: dict, per: str, pl: dict = None,
              capital: float = 1_000_000, vol_target=15.0,
              hold: dict = None, turn: dict = None) -> str:
    """Weights, the size they imply, and what that size actually fills.

    All the arithmetic arrives done: sk_portfolio.plan holds the weights,
    dollars, contracts and the as-filled rescore, because every one of those
    needs the return matrix and none of them should be recomputed by a
    renderer working from a payload.
    """
    if not res or not res.get("weights"):
        return ('<div class="skel">No portfolio yet — set the objective and '
                "press Optimize.</div>")
    t = _tok()
    pl = pl or {}
    ink = t.get("ink", "#0d1418")
    teal, amber = t.get("teal", "#0d8f83"), t.get("amber", "#96701c")
    faint, mute = t.get("faint", "#97a2ab"), t.get("mute", "#66727b")
    pos = t.get("pos", "#0a7c66")
    # Everything quoted AT THE SIZE HELD. The unit-gross basket is a shape,
    # not a position: its Vol% is whatever the legs happen to make, which is
    # why a 20% target used to sit beside a 31.5% volatility.
    st_ = pl.get("sized") or res["stats"]
    eq = pl.get("sizedEqual") or res["equal"]
    filled = pl.get("filled")
    legs = pl.get("legs") or [dict(w, notional=None, fill=None)
                              for w in res["weights"]]
    lev, gross = pl.get("lev", 0), pl.get("gross", 0)

    line = " · ".join(f'{w["code"]} {w["w"]:+.0f}%' for w in res["weights"])

    # Under half the account in margin is room to be wrong; past three
    # quarters there is no room left for a bad day, let alone another trade.
    mpc = pl.get("marginPct", 0)
    mcol = ink if mpc < 50 else (amber if mpc < 75 else t.get("neg", amber))
    def riskcell(rk, code_):
        """The variance share, coloured — it was the greyest thing on the row.

        This is the column that catches a basket which is one bet wearing five
        hedges, and it was rendered `dim` beside a Weight column in full ink.
        A negative share is a leg taking variance OUT of the portfolio, which
        is the good side and so reads teal; a positive one past 40% is a
        concentration the weight cap cannot see, so it takes the same amber
        the Miss column uses for a fill that has drifted off its leg.
        """
        if rk is None:
            return '<td class="faint">—</td>'
        if rk < 0:
            col_, wt = teal, 550
        elif abs(rk) >= 60:
            col_, wt = amber, 700
        elif abs(rk) >= 40:
            col_, wt = amber, 550
        else:
            col_, wt = mute, 450
        tip_ = (f'{code_} carries {rk:.1f}% of the portfolio variance'
                + (" — it hedges, so it takes risk out" if rk < 0 else ""))
        return (f'<td style="color:{col_};font-weight:{wt}" '
                f'title="{esc(tip_)}">{rk:.1f}</td>')

    rows = ""
    for i, leg in enumerate(legs, 1):
        long_ = leg["w"] >= 0
        col = teal if long_ else amber
        code = leg["code"]
        f = leg.get("fill") or {}
        err = f.get("err")
        # The fill's error is the cost of having chosen weights first. Amber
        # past 10% because that is where a hedge stops being the hedge that
        # was ranked.
        ecol = amber if (err is not None and abs(err) >= 10) else mute
        tip = ""
        if leg.get("unit"):
            tip = f'one {code} is ${leg["unit"]:,.0f}'
            if leg.get("smallUnit"):
                tip += f' · one {leg["small"]} is ${leg["smallUnit"]:,.0f}'
            tip += f' · target ${abs(leg["notional"]):,.0f}'
            if leg.get("needs"):
                tip += (f' · fills from about ${leg["needs"]:,.0f} of '
                        f'capital at this weight')
        # No ordinal and no weight bar. Both were carrying nothing a neighbour
        # did not already say — the rows are in weight order and the bar was
        # drawing the number next to it — and the width is better spent on the
        # nine columns that answer something.
        rows += (f'<tr><td class="l">'
                 f'{swatch(U.SECTOR.get(code, ""))}{esc(code)} '
                 f'<span class="nm">{esc(U.NAME.get(code, ""))}</span></td>'
                 f'<td class="l" style="color:{col};font-weight:600">'
                 f'{"long" if long_ else "short"}</td>'
                 f'<td style="color:{ink};font-weight:700">'
                 f'{abs(leg["w"]):.1f}%</td>'
                 + riskcell(leg.get("risk"), code)
                 + (f'<td class="dim">{abs(leg["notional"]):,.0f}</td>'
                    if leg.get("notional") is not None
                    else '<td class="faint">—</td>')
                 + (f'<td class="l" style="color:{ink};font-weight:600" '
                    f'title="{esc(tip)}">{esc(f.get("text", "—"))}</td>'
                    f'<td style="color:{ecol}">'
                    f'{"—" if err is None else f"{err:+.1f}%"}</td>'
                    + (f'<td class="dim">{f["fee"]:,.0f}</td>'
                       if f.get("fee") else '<td class="faint">—</td>')
                    + (f'<td class="dim">{leg["margin"]:,.0f}</td>'
                       if leg.get("margin") else '<td class="faint">—</td>')
                    if f else '<td class="l faint">—</td>'
                              '<td class="faint">—</td><td class="faint">—</td>'
                              '<td class="faint">—</td>')
                 + "</tr>")
    if pl:
        got = (pl.get("filled") or {}).get("gross") or 0
        # `out` is the raised band the other tabs use for a summary row. The
        # two totals sat in plain body rows and read as a seventh and eighth
        # leg until the eye reached the word "exposure".
        rows += (f'<tr class="out"><td class="l dim">Gross exposure</td>'
                 f'<td class="l dim">{lev:.2f}×</td>'
                 f'<td class="dim">100.0%</td>'
                 f'<td class="dim">100.0</td>'
                 f'<td style="color:{ink};font-weight:700">'
                 f'{pl.get("target", 0):,.0f}</td>'
                 f'<td class="l dim">{got:,.0f} filled</td>'
                 f'<td class="faint">on {capital:,.0f}</td>'
                 f'<td style="color:{ink};font-weight:700">'
                 f'{pl.get("fees", 0):,.0f}</td>'
                 f'<td style="color:{mcol};font-weight:700">'
                 f'{pl.get("margin", 0):,.0f}</td></tr>')
        # Net is the direction the basket leans. Gross says how much is
        # working, net says how much of it is a bet on everything going the
        # same way — a market-neutral pair and an outright double long can
        # carry identical gross and could not be less alike.
        net_d = sum(l["notional"] for l in legs if l.get("notional") is not None)
        net_pc = net_d / capital * 100 if capital else 0
        nfill = sum((l["fill"] or {}).get("notional") or 0 for l in legs)
        ncol = pos if abs(net_pc) < 25 else amber
        rows += (f'<tr class="out"><td class="l dim">Net exposure</td>'
                 f'<td class="l dim" style="color:{ncol}">'
                 f'{"long" if net_d >= 0 else "short"}</td>'
                 f'<td class="dim">{res["net"]:+.1f}%</td>'
                 f'<td class="faint">—</td>'
                 f'<td style="color:{ncol};font-weight:700">'
                 f'{net_d:+,.0f}</td>'
                 f'<td class="l dim">{nfill:+,.0f} filled</td>'
                 f'<td class="faint">{net_pc:+.0f}% of capital</td>'
                 f'<td class="faint">—</td>'
                 f'<td style="color:{mcol}">{pl.get("marginPct", 0):.0f}% '
                 f'of capital</td></tr>')

    def statrow(label, d, strong, note_="", wash=""):
        if not d:
            return ""
        cells = "".join(
            f'<td style="{wash}color:{col or ink};'
            f'font-weight:{700 if strong else 600}">{v}</td>'
            for v, col in (
                (num(d.get("erAdj"), 2), None), (num(d.get("roa"), 1), None),
                (num(d.get("sharpe"), 2), None),
                (f'{d.get("win", 0):.0f}', None), (num(d.get("vol"), 1), None),
                (f'{"+" if (d.get("tot") or 0) >= 0 else ""}'
                 f'{num(d.get("tot"), 1)}',
                 pos if (d.get("tot") or 0) >= 0 else amber),
                (num(d.get("mdd"), 1), amber)))
        tail = (f'<span class="nm" style="color:{mute}"> {esc(note_)}</span>'
                if note_ else "")
        return (f'<tr><td class="l" style="{wash}">{esc(label)}{tail}</td>'
                f'{cells}</tr>')

    curve, eqc = res["curve"], res["equalCurve"]
    exc = pl.get("execCurve")
    # The three rows of the table, drawn. Two of them are arguments and one is
    # the position, so only one is solid: teal, the basket in whole contracts,
    # is what can be sent and it sits on top. The ideal is the same shape
    # before rounding, amber and dotted because it is the claim rather than
    # the answer; equal weight is ink, dotted and at half strength — which
    # resolves to white on the dark theme and near-black on the light one, so
    # it reads as a reference in both. Ink and faint at chart weight was grey
    # against grey and could not say which line was the answer; faint alone
    # was too close to the gridlines to be seen as a line at all.
    #
    # Back to front: the reference under the claim, the claim under the
    # position. Nothing solid is ever crossed out by a dotted line.
    ideal = ({"k": "optimized (ideal weights)", "v": curve["v"], "c": amber,
              "w": 2.0, "dash": "0.1 5", "cap": "round", "o": 0.95}
             if exc else
             # No fill to draw — an unpriced basket, or one no leg reaches.
             # The ideal is then the only answer on screen, so it stops
             # deferring to a line that is not there.
             {"k": "optimized (ideal weights)", "v": curve["v"], "c": amber,
              "w": 2.6})
    series = [{"k": "equal weight, same legs", "v": eqc["v"], "c": ink,
               "w": 1.8, "dash": "0.1 5", "cap": "round", "o": 0.55},
              ideal]
    if exc:
        series.append({"k": "executable (whole contracts)", "v": exc["v"],
                       "c": teal, "w": 2.6})
    # Legend in the table's order — optimized, executable, equal weight — so
    # the two halves of the card are read the same way down.
    legend = "".join(
        f'<span class="key" style="display:inline-flex;align-items:center;'
        f'gap:6px"><i style="display:inline-block;width:18px;height:0;'
        f'border-top:{"2px dotted" if sr.get("dash") else "3px solid"} '
        f'{sr["c"]};opacity:{sr.get("o", 1)}"></i>'
        f'<span style="color:{sr["c"]};opacity:{sr.get("o", 1)};'
        f'font-weight:600">{esc(sr["k"])}</span></span>'
        for sr in ([ideal] + series[2:] + series[:1]))

    # What the picture is for, said in words. Two numbers, because they answer
    # two different questions and the tab would be dishonest carrying only one:
    # the OBJECTIVE delta is what the search actually maximised and what the
    # weights were chosen on, and the end-of-curve gap is what the lines on
    # screen literally show. They can disagree — a basket can win on ROA by
    # taking a shallower hole rather than by making more — and when they do,
    # that disagreement is the finding.
    okey = {"ROA": "roa", "ER (Adj)": "erAdj", "Sharpe": "sharpe"}.get(
        res.get("objective"), "roa")
    ov, bv = st_.get(okey), eq.get(okey)
    odel = (None if ov is None or not bv else (ov - bv) / abs(bv) * 100)
    if odel is None:
        verdict = (f'<span style="color:{faint}">{esc(per)} · '
                   f'{len(curve["t"])} bars</span>')
    else:
        beats = odel >= 0
        vcol = pos if beats else amber
        verdict = (f'<span style="padding:2px 8px;border-radius:3px;'
                   f'background:{vcol}22;color:{vcol};font-weight:700;'
                   f'font-size:10.5px;letter-spacing:.04em;white-space:nowrap">'
                   f'{"BEATS" if beats else "LOSES TO"} EQUAL WEIGHT '
                   f'{"+" if beats else ""}{odel:.0f}% ON '
                   f'{esc(res.get("objective", "").upper())}</span>')
    # Rebased to 100 at the left edge, both of them, so the difference of the
    # two end points IS the gap in percentage points over the window. Read off
    # the drawn series rather than off the stats, because the stats are quoted
    # at the size held and these lines are not.
    cend = curve["v"][-1] if curve["v"] else None
    eend = eqc["v"][-1] if eqc["v"] else None
    xend = exc["v"][-1] if (exc and exc["v"]) else None
    # The executable end point goes beside the ideal rather than in place of
    # it: the distance between those two is the price of whole contracts, and
    # it is the one number the third line was added to make visible.
    gap = (f'ends at {cend:,.1f} ideal'
           + (f', {xend:,.1f} executable' if xend is not None else "")
           + f' vs {eend:,.1f} equal — '
             f'{(xend if xend is not None else cend) - eend:+,.1f} points '
             f'over the window'
           if cend is not None and eend is not None else "")
    plotsub = " · ".join(x for x in (
        f'{esc(per)} · {len(curve["t"])} bars',
        (f'{esc(res.get("objective", ""))} {num(ov, 2)} vs {num(bv, 2)}'
         if odel is not None else ""),
        gap) if x)

    # The score and its curve share the top band, and the weights run the full
    # width underneath. The conclusion is one thing said twice — four rows of
    # numbers and the line they came off — so it reads across, not down; the
    # weights are the working, and the working goes last.
    # Two facts outlived the chip row they used to live in, and both belong on
    # this line rather than in a block of their own: the size the table is
    # quoted at, and whether it is still the same basket as last time.
    held = f"held at {pl.get('lev', 0):.2f}×"
    turned = (f'{turn["kept"]} of {turn["of"]} legs held · '
              f'{turn["turnover"]:.0f}% turnover since the last run'
              if turn else "")

    # The vol target was the one control with nothing on screen to answer it.
    # A 30% target on a quiet basket asks for 6.8x, the 1x cap refuses, and
    # the table then reports 4.4% volatility — a seventh of the risk the
    # control was set to — while the card said only "capped from 6.82x". The
    # cap was named and the thing it cost was not. Trends already reconciles
    # these two numbers in one clause and this says it the same way, with the
    # cap moved down beside it: the cap is the reason for the miss, so the two
    # belong on one line rather than at opposite ends of the card.
    volat = pl.get("volAt")
    size_bits = []
    if volat is not None and vol_target:
        miss = abs(volat - vol_target) >= 1
        vc = amber if miss else pos
        size_bits.append(
            f'<span style="color:{vc};font-weight:{700 if miss else 600}">'
            f'holds {volat:.1f}% vol {"of" if miss else "at"} the '
            f'{vol_target:.0f}% target</span>')
    elif volat is not None:
        size_bits.append(f'<span style="color:{mute}">holds {volat:.1f}% vol '
                         f'— sized on leverage, not on a vol target</span>')
    if pl.get("capped"):
        size_bits.append(f'<span style="color:{amber}">capped at '
                         f'{pl.get("lev", 0):.2f}× from '
                         f'{pl.get("wantLev", 0):.2f}×</span>')
    sep = f'<span style="color:{faint}">·</span>'
    sizeline = (f'<div class="cstats" style="margin-bottom:5px">'
                f'{sep.join(size_bits)}</div>' if size_bits else "")

    # The legs no fill can reach, counted and named. Every such row already
    # shows its own em-dash in the Fill column, but nothing added them up, and
    # a basket missing two of six legs is not the basket the table above it
    # scored — the Executable row is washed green for being the one that is
    # true, and it is only true if you know what is missing from it. The
    # capital figure is the largest of the per-leg thresholds, so it is the
    # number at which the WHOLE basket fills rather than the next leg.
    und = pl.get("undersized") or []
    warn = ""
    if und and legs:
        # "A, B and C" rather than "A, B, C": this is a sentence, and the
        # list is short enough to be read as one.
        named = (" and ".join(und) if len(und) < 3
                 else ", ".join(und[:-1]) + " and " + und[-1])
        needs = [l.get("needs") for l in legs
                 if l["code"] in und and l.get("needs")]
        at = (f' · the whole basket fills from about ${max(needs):,.0f}'
              if needs else "")
        warn = (f'<div style="margin:0 0 8px;padding:5px 9px;border-radius:4px;'
                f'background:{amber}1a;color:{amber};font-size:10.5px;'
                f'font-weight:600;line-height:1.5">'
                f'{esc(named)} cannot be sent at ${capital:,.0f} — '
                f'{len(und)} of {len(legs)} legs{esc(at)}</div>')

    scored = (statrow("Optimized", st_, False)
              # Executable, not "as filled": it is the row you can send, and
              # it is washed green because it is the one that is true. The
              # ideal above it is the argument for it.
              + statrow("Executable", filled, True,
                        wash=f"background:{pos}1f;")
              + statrow("Equal weight", eq, False)
              # The row that says how fast a fit like this decays: the weights
              # never saw these bars. Amber when the tail is too short to
              # carry an opinion.
              + statrow("Held forward", (hold or {}).get("stats"), False,
                        wash=(f"background:{amber}14;"
                              if (hold or {}).get("thin") else "")))
    # The notes that used to trail each label are one line under the title
    # instead. Wrapping the label column to three lines pushed the numbers off
    # the right edge, and half a page is still not room for both.
    sub = " · ".join(x for x in (
        "ideal vs whole contracts vs equal weight",
        (f'held forward fit on {hold["trainBars"]} bars through '
         f'{hold["testBars"]}') if hold else "", turned) if x)

    # A bare table, not table(): inside the card its border would be a second
    # rectangle drawn 14px inside the first one.
    #
    # Four lines above the numbers, in the order a reader needs them: what the
    # card is and the size it is quoted at, whether that size hit the risk
    # that was asked for, what cannot be sent at all, and last — quietest —
    # where the rows came from. The three facts that carry colour used to be
    # one grey run-on sentence with the provenance, which is the one thing on
    # the card nobody needs to read twice.
    card = ('<div class="plot">'
            f'<div class="ctitle"><b>What this portfolio scored</b>'
            f'<span>{esc(held)}</span></div>'
            + sizeline + warn
            + (f'<div class="cstats" style="color:{mute}">{esc(sub)}</div>'
               if sub else "")
            + '<div class="scroll"><table>'
              '<thead><tr><th class="l"></th><th>ER adj</th><th>ROA</th>'
              '<th>Sharpe</th><th>Win%</th><th>Vol%</th><th>Tot%</th>'
              '<th>MDD%</th></tr></thead>'
              f'<tbody>{scored}</tbody></table></div>'
            + "</div>")

    # The picture is its own card beside the table rather than a second half
    # of it. Same head, same border, and a title that says what it is drawing
    # — the legend names the two lines, not what they are for.
    plot = ('<div class="plot">'
            '<div class="ctitle"><b>The curve behind the score</b>'
            f'{verdict}</div>'
            + f'<div class="clegend">{legend}</div>'
            + f'<div class="cstats" style="color:{mute}">{plotsub}</div>'
            + CH.line_chart(curve["t"], series, None, 620, 300, 1)
            + "</div>")

    weights = ('<div>'
               + eyebrow(f"Portfolio Weights — {esc(res['objective'])}, "
                         f"{esc(per)}",
                         f'<span style="margin-left:auto;color:{mute};'
                         f'font-size:11.5px;font-weight:500">{esc(line)}'
                         f'</span>')
               + table('<th class="l">Instrument</th>'
                       '<th class="l">Side</th><th>Weight</th>'
                       '<th title="Share of portfolio variance. Sums to 100 '
                       'across the legs; a hedge reads negative.">Risk%</th>'
                       # Four of these columns are dollars and three of them
                       # were not saying so, which left Miss — the one that is
                       # a percentage — looking like the odd one out.
                       '<th>Notional $</th>'
                       '<th class="l">Fill</th><th>Miss%</th><th>Fees $</th>'
                       '<th>Margin $</th>', rows)
               + '</div>')
    return f'<div class="pfgrid">{card}{plot}</div>{weights}'



def freshness(stamp, ttl: int) -> str:
    """How old this field is, and how long until it refetches on its own.

    Presentation, so it sits beside the chips that show it. The stamp is taken
    inside the cached builder, so it reports when the data was BUILT — a page
    reload advances this countdown while leaving every number untouched, which
    is the whole confusion it exists to answer.
    """
    if not stamp:
        return ""
    import datetime as _dt
    age = int((_dt.datetime.now(_dt.timezone.utc) - stamp).total_seconds())
    left = max(ttl - age, 0)
    ago = "just now" if age < 60 else f"{age // 60}m ago"
    return (f"computed {ago} · refreshes itself in {left // 60}m {left % 60}s"
            if left else f"computed {ago} · due to refresh")


def spreads(d: dict, per: str, sort: str = DEFAULT_SORT,
            fresh: str = "", capital: float = 1_000_000.0,
            vol_target: float = 30.0, smalls: bool = True,
            max_lev: float | None = 1.0) -> str:
    p = d["data"][per]
    t = _tok()

    # Reading order: best spread per window, then how the single instruments
    # did, then the full field for the window you picked, then the pictures.
    out = _optimal(d, per, t, sort) + _outrights(d, per, t, sort)

    teal = t.get("teal", "#0d8f83")
    amber = t.get("amber", "#96701c")
    # The column follows its own selector; "Match basis" tracks the maths.
    weighting = WEIGHTINGS.get(d.get("mode", "vol"), WEIGHTINGS["vol"])
    skey, sxkey = weighting["keys"]
    key = SORTS.get(sort, SORTS[DEFAULT_SORT])
    rows = sorted(p["rows"], key=lambda r: -(r.get(key) if r.get(key)
                                             is not None else -9e9))
    # Tot% and MDD% adjacent: they are the same question asked twice, what you
    # made and what you gave back on the way.
    head = ('<th class="l">#</th><th class="l">Long</th><th class="l">Short</th>'
            '<th>ER</th><th>ER (Adj)</th><th>Win%</th><th>Vol%</th>'
            '<th>Tot%</th><th>MDD%</th><th>ROA</th>'
            f'<th class="l">Send ({esc(weighting["label"])})</th>'
            '<th>vs leg</th><th>Top 10</th>')
    body = ""
    for i, r in enumerate(rows, 1):
        lg = (f'<span style="color:{teal};font-weight:600">{esc(r["long"])}'
              f'</span>' if r["long"] else '<span class="cash">cash</span>')
        sh = (f'<span style="color:{amber};font-weight:600">{esc(r["short"])}'
              f'</span>' if r["short"] else '<span class="cash">cash</span>')
        dv = r.get("legDelta")
        if dv is None:
            legcell = '<td class="faint">—</td>'
        else:
            # The column that decides whether the second ticket was worth it,
            # so beating the leg gets a wash rather than only coloured text.
            beat = dv >= 0
            wash = (f'background:{t.get("pos", "#0a7c66")}1f' if beat else "")
            legcell = (f'<td class="{"pos" if beat else "warn"}" '
                       f'style="{wash}">{"+" if beat else ""}{dv:.0f}%</td>')
        # The order, at the account on screen. A ratio is scale-free and a
        # ticket is not: "1 GC : 2.34 SI" is true at a million dollars and at
        # five thousand, and sendable at neither — the number of contracts is
        # the first thing that says whether this window's best idea fits in
        # the account at all. Contracts also carry what the sigma ratio could
        # not: a 6J contract is $78k of notional against $24k for ZC, so
        # matching volatility was never matching size, and the column now
        # shows the size.
        #
        # The exact ratio it targets, how far the fill's hedge lands from it,
        # and the leverage it takes all sit on hover rather than widening a
        # row that already carries eleven columns.
        sz = SP.size_at(r, capital, vol_target, p.get("ann") or 252,
                        smalls=smalls, max_lev=max_lev)
        ex = r.get(sxkey)
        if sz and sz["text"] != "—":
            tip = []
            if ex:
                tip.append(f'ratio 1 {r["long"]} : {1 / ex:,.2f} {r["short"]}')
            if sz.get("hedge") is not None:
                tip.append(f'hedge {sz["hedge"]:+.1f}% off that')
            tip.append(f'{sz["lev"]:.2f}x gross, holds {sz["volAt"]:.0f}% vol'
                       + (f' — capped from {sz["wantLev"]:.2f}x'
                          if sz.get("capped") else ""))
            size = (f'<td class="l dim" title="{esc(" · ".join(tip))}">'
                    f'{esc(sz["text"])}</td>')
        elif ex:
            size = (f'<td class="l faint" title="does not fill at '
                    f'{capital:,.0f}">1 : {1 / ex:,.2f}</td>')
        else:
            size = '<td class="l faint">—</td>'
        # A count, not a list of names. The names are still there on hover for
        # the one row in twenty where you want to know which.
        also = r.get("alsoTop") or []
        alsocell = ('<td class="faint">—</td>' if not also else
                    f'<td class="dim" title="{esc(" ".join(also))}">'
                    f'{len(also)}</td>')
        body += (f'<tr class="{"out" if r["kind"] == "outright" else ""}">'
                 f'<td class="l faint">{i}</td><td class="l">{lg}</td>'
                 f'<td class="l">{sh}</td>'
                 + cell(r["er"], 3, "dim") + cell(r.get("erAdj"), 2, "last")
                 + cell(r["win"], 0, "dim") + cell(r["vol"], 1, "dim")
                 + pct(r["tot"], 1) + cell(r["mdd"], 1, "warn")
                 + cell(r.get("roa"), 1, "last")
                 + size + legcell + alsocell + "</tr>")

    return (out
            + eyebrow(f"Spreads by Time Window — {esc(per)}, ranked on "
                      f"{esc(sort)}, "
                      + ("vol-adjusted legs" if d.get("mode") == "vol"
                         else "equal-notional legs"))
            + table(head, body)
            # The last two chips follow the basis. They were hardcoded, so
            # notional mode still claimed vol-adjusted legs and advertised a
            # 5:1 cap that apply_ratio_cap does not apply in that mode.
            + chips([p["note"], f'{p["bars"]} bars · {p["instruments"]} '
                     f'instruments', f'{p["start"]} → {p["end"]}']
                    # MDD is the one column measured on something other than
                    # the window's own bar, so the window says so.
                    + ([f'MDD on {p["ddBars"]:,} {p["ddBar"]} marks']
                       if p.get("ddBar") else [])
                    + (["vol-adjusted legs", f'cap {d["cap"]}:1']
                       if d.get("mode") == "vol" else
                       ["equal-notional legs", "no leg cap"])
                    + ([fresh] if fresh else []))
            + spread_charts(p, t, sort, capital, vol_target, smalls,
                            max_lev))


def spread_charts(p: dict, t: dict = None, sort: str = DEFAULT_SORT,
                  capital: float = 1_000_000.0, vol_target: float = 30.0,
                  smalls: bool = True, max_lev: float | None = 1.0) -> str:
    """Legs rebased to 100 in the side colours, spread over them in the ink.

    The grid follows the table: same ranking, same order, same twelve. The
    payload carries every ranking's candidates, so this reproduces the pick
    rather than recomputing it — a chart cannot be drawn from here, only
    chosen.
    """
    if not p.get("charts"):
        return ""
    key = SORTS.get(sort, SORTS[DEFAULT_SORT])
    ranked = sorted(p["charts"], key=lambda c: -(c.get(key) if c.get(key)
                                                 is not None else -9e9))
    picked = ranked[:p.get("chartCap", 12)]
    mode = p.get("mode", "vol")
    t = t or _tok()
    ink = t.get("ink", "#0d1418")
    teal, amber = t.get("teal", "#0d8f83"), t.get("amber", "#96701c")
    # Amber, not red: a spread losing to its leg is a worse choice, not a
    # blown-up one, and red is no longer used for numbers anywhere.
    neg, pos = t.get("amber", "#96701c"), t.get("pos", "#0a7c66")
    faint = t.get("faint", "#97a2ab")
    cards = ""
    for n, c in enumerate(picked, 1):
        series = []
        if c.get("lg"):
            series.append({"k": c["lgName"], "v": c["lg"], "c": teal,
                           "w": 1.6, "o": 0.95})
        if c.get("sh"):
            series.append({"k": c["shName"], "v": c["sh"], "c": amber,
                           "w": 1.6, "o": 0.95})
        series.append({"k": "spread", "v": c["sp"], "c": ink, "w": 2.6})
        # Legend keys are LINE segments, not squares — they stand for lines,
        # and the label carries the same colour so the eye pairs them.
        legend = "".join(
            f'<span class="key" style="display:inline-flex;align-items:center;'
            f'gap:6px"><i style="display:inline-block;width:16px;height:3px;'
            f'border-radius:2px;background:{s["c"]}"></i>'
            f'<span style="color:{s["c"]};font-weight:600">{esc(s["k"])}</span>'
            f'</span>' for s in series)

        dv = c.get("legDelta")
        if dv is None:
            verdict = ""
        else:
            beats = dv >= 0
            col = pos if beats else neg
            verdict = (
                f'<span style="margin-left:auto;padding:2px 8px;'
                f'border-radius:3px;background:{col}22;color:{col};'
                f'font-weight:700;font-size:10.5px;letter-spacing:.04em;'
                f'white-space:nowrap">'
                f'{"BEATS" if beats else "LOSES TO"} BEST LEG '
                f'{"+" if beats else ""}{dv:.0f}%</span>')

        # The same risk columns the table carries, so a shape you like can be
        # checked here rather than by hunting for its row.
        def stat(label, val, suffix="", col=None, on=None):
            if val is None:
                return ""
            live = (on or label) == RANKED_AS.get(key)
            return (f'<span style="white-space:nowrap"><span style="color:'
                    f'{ink if live else faint};font-size:9px;'
                    f'letter-spacing:.07em;font-weight:{600 if live else 400};'
                    f'text-transform:uppercase">{label}</span> '
                    f'<span style="color:{col or ink};'
                    f'font-weight:{700 if live else 600}">'
                    f'{val}{suffix}</span></span>')

        stats = "".join([
            stat("ER (Adj)", c.get("erAdj")),
            stat("ROA", c.get("roa")),
            stat("Sharpe", c.get("sharpe")),
            stat("Win", c.get("win"), "%", on="Win%"),
            stat("Vol", c.get("vol"), "%"),
            stat("MDD", c.get("mdd"), "%", neg),
            stat("Tot", (f'{"+" if (c.get("tot") or 0) >= 0 else ""}'
                         f'{c.get("tot")}') if c.get("tot") is not None
                 else None, "%", pos if (c.get("tot") or 0) >= 0 else neg,
                 on="Tot%"),
        ])
        # The line the ratio was always missing. A card that says "1 GC :
        # 2.34 SI" has told you the shape and nothing about whether you can
        # hold it: the same sentence is true for a million-dollar account and
        # a five-thousand-dollar one, and only one of them can send it. So the
        # ratio is quoted against the account and the vol target on screen —
        # the contracts to send, the gross it takes, the volatility the ROUNDED
        # position actually runs at, and how far its hedge landed from the one
        # the field was ranked on.
        #
        # The vol target does not touch the ratio, which is the point worth
        # seeing: 20% instead of 30% buys two thirds of both legs, same mix.
        # It moves the hedge only through rounding, and it moves it most on
        # the small account — which is exactly where a spread quietly stops
        # being a spread, and exactly what the old display could not say.
        sz = SP.size_at(c, capital, vol_target, p.get("ann") or 252,
                        smalls=smalls, max_lev=max_lev)
        if not sz or sz["text"] == "—":
            sized = ""
        else:
            hv = sz.get("hedge")
            # Under 2% is inside the noise of a sigma sampled off a few dozen
            # bars, so it is not worth colouring. Past 10% the position being
            # held is not the one that ranked.
            hcol = (faint if hv is None or abs(hv) < 2
                    else (neg if abs(hv) >= 10 else ink))
            hedge = ("" if hv is None else
                     f'<span style="white-space:nowrap"><span style="color:'
                     f'{faint};font-size:9px;letter-spacing:.07em">HEDGE</span> '
                     f'<span style="color:{hcol};font-weight:'
                     f'{700 if hcol == neg else 600}">{hv:+.0f}%</span></span>')
            # Colour follows what is HELD, not what was asked for. Above 3x
            # the vol target is being reached with borrowed room rather than
            # with the position, which is a different decision and deserves
            # the warning; a position the cap already pulled back to 1x is
            # carrying no such risk, however much the sizing wanted. What it
            # wanted still shows — as text, beside it.
            lcol = neg if sz["lev"] >= 3 else faint
            grossv = (f'{sz["lev"]:.2f}×'
                      + (f'<span style="color:{faint};font-weight:500"> '
                         f'of {sz["wantLev"]:.1f}× asked</span>'
                         if sz.get("capped") else ""))
            sized = (f'<div class="cstats" style="gap:3px 10px">'
                     f'<span style="white-space:nowrap"><span style="color:'
                     f'{faint};font-size:9px;letter-spacing:.07em;'
                     f'font-weight:600">SEND</span> <span style="color:{ink};'
                     f'font-weight:700">{esc(sz["text"])}</span></span>'
                     f'<span style="white-space:nowrap"><span style="color:'
                     f'{faint};font-size:9px;letter-spacing:.07em">GROSS</span> '
                     f'<span style="color:{lcol};font-weight:600">'
                     f'{grossv}</span></span>'
                     f'<span style="white-space:nowrap"><span style="color:'
                     f'{faint};font-size:9px;letter-spacing:.07em">HOLDS</span> '
                     f'<span style="color:{ink};font-weight:600">'
                     f'{sz["volAt"]:.0f}%</span>'
                     # Only worth naming the target when the fill missed it,
                     # and only worth colouring when the MISS is a surprise.
                     # "30% of 30% asked" says one thing twice. "39% of 30%
                     # asked" is rounding losing the target on an account too
                     # small to express it, which is the whole point of the
                     # line. A capped position missing by 27 points is neither
                     # — it is the cap doing exactly what it was set to do,
                     # already said one field to the left, and painting twelve
                     # cards amber for it is how a warning stops being read.
                     + (f' <span style="color:{neg}">of {vol_target:.0f}% '
                        f'asked</span>'
                        if not sz.get("capped")
                        and abs(sz["volAt"] - vol_target) >= 1 else "")
                     + f'</span>{hedge}</div>')

        cards += (f'<div class="plot"><div class="ctitle">'
                  f'<b>{n}. {esc(c["label"])}</b>'
                  # The verdict was already reaching for the far corner with
                  # margin-left:auto; on the title row it gets one, and the
                  # name has the row to itself now that its number moved down
                  # into the stat line with the rest of them.
                  f'{verdict}</div>'
                  f'<div class="clegend">{legend}</div>'
                  f'<div class="cstats">{stats}</div>'
                  f'{sized}'
                  + CH.line_chart(c["t"], series, None, 560, 220, 1) + "</div>")
    return (eyebrow("Why they ranked",
                    f'<span style="margin-left:auto;color:{faint};'
                    f'font-size:11.5px;font-weight:500">sized for '
                    f'${capital:,.0f} at {vol_target:.0f}% vol, '
                    + (f'{max_lev:g}× gross at most' if max_lev
                       else 'no leverage cap')
                    + '</span>')
            + f'<div class="cgrid">{cards}</div>')

# ------------------------------------------------------------------ Curve
def curve(d: dict, code: str) -> str:
    curves = d.get("curves", {})
    flag = (f'<div class="flag">{esc(d["warn"])}</div>'
            if d.get("warn") else "")
    if not curves:
        return (flag + '<div class="skel">No settlement data — CME may have '
                "refused this host. Try Refresh.</div>")
    # `or -99` turned a carry of exactly 0.0 into -99 and sank a flat curve to
    # the bottom with the missing data. None is the only thing that belongs
    # there, so sort on an explicit None test.
    scan = sorted(curves.values(),
                  key=lambda r: (r.get("carryAnn") is None,
                                 -(r["carryAnn"] if r.get("carryAnn")
                                   is not None else 0.0)))
    head = ('<th class="l">Symbol</th><th class="l">Sector</th><th>Front</th>'
            '<th>Back</th><th class="l">Span</th><th class="l">Shape</th>'
            '<th>Roll %</th><th>Carry ann %</th>')

    def shape_cls(s):
        # Flat is not bearish. Colouring anything-not-Backwardation red painted
        # a flat curve the same as a contangoed one.
        return {"Backwardation": "pos", "Contango": "neg"}.get(s, "dim")

    body = "".join(
        f'<tr><td class="l">{esc(r["code"])}</td>'
        f'<td class="l faint">{esc(r["sector"])}</td>'
        # Per-instrument decimals: a hardcoded 2 rendered every 6J settlement
        # as "0.01".
        + cell(r["front"], U.DEC.get(r["code"], 2), "dim")
        + cell(r["back"], U.DEC.get(r["code"], 2), "dim")
        + f'<td class="l faint">{r.get("spanMonths", "—")}m</td>'
        + f'<td class="l {shape_cls(r["shape"])}">{esc(r["shape"])}</td>'
        + pct(r["rollPct"], 2) + pct(r["carryAnn"], 1) + "</tr>"
        for r in scan)

    c = curves[code]
    dec = U.DEC.get(code, 2)
    months = [r["month"] for r in c["rows"]]
    settle = [r["settle"] for r in c["rows"]]
    oi = []
    for r in c["rows"]:
        try:
            oi.append(float(str(r.get("oi", "")).replace(",", "")))
        except ValueError:
            oi.append(None)
    arrow = ("↘" if c["shape"] == "Backwardation"
             else "↗" if c["shape"] == "Contango" else "→")
    detail = "".join(
        f'<tr><td class="l">{esc(r["month"])}</td>' + cell(r["settle"], dec)
        + f'<td class="dim">{esc(r.get("chg") or "—")}</td>'
        f'<td class="dim">{esc(r.get("vol") or "—")}</td>'
        f'<td class="dim">{esc(r.get("oi") or "—")}</td></tr>'
        for r in c["rows"])

    return (flag
            + note("CME settlements"
                 + (f' · {esc(d.get("tradeDate"))}' if d.get("tradeDate")
                    else "")
                 + ". Back month is the furthest with real open interest; "
                   "positive carry is backwardation.")
            + eyebrow("Carry scanner — most backwardated first")
            + table(head, body)
            + note(f'<b>{esc(c["code"])}</b> · {esc(c["frontMonth"])} '
                   f'<b>{num(c["front"], dec)}</b> → {esc(c["backMonth"])} '
                   f'<b>{num(c["back"], dec)}</b> over '
                   f'{c.get("spanMonths", "?")}m (OI '
                   f'{num(c.get("backOI"), 0) or "—"}) · {esc(c["shape"])} '
                   f'{arrow} · roll {"+" if (c["rollPct"] or 0) >= 0 else ""}'
                   f'{num(c["rollPct"], 2)}% · carry ann '
                   f'{"+" if (c["carryAnn"] or 0) >= 0 else ""}'
                   f'{num(c["carryAnn"], 1)}%')
            + '<div class="plot">'
            + CH.line_chart(months,
                            [{"k": "Settle", "v": settle, "c": C["teal"],
                              "w": 2.4}], oi, 1100, 280, dec) + "</div>"
            + eyebrow("Settlements")
            + table('<th class="l">Month</th><th>Settle</th><th>Change</th>'
                    "<th>Volume</th><th>OI</th>", detail))


# ---------------------------------------------------------------- Margins
# "Sector" is the odd one out: it ranks on a string, so it sorts on the
# universe's own order rather than alphabetically — Indices, Bonds,
# Currencies, Crypto, then Energy, Metals, Grains, Softs — and breaks ties
# inside a sector on HV percentile. It is the one sort that gives back the
# Financials/Commodities grouping the merge took away, for the times you want
# to read the book by class rather than by extreme.
MARGIN_SORTS = {
    "HV %ile": ("volPct", True),
    "ATR %ile": ("atrPct", True),
    "Leverage": ("lev", True),
    "Days ATR": ("daysATR", False),
    "HV 20d": ("annVol", True),
    "ATR $": ("atr", True),
    "Notional": ("notional", True),
    "Maint $": ("maint", True),
    "Sector": ("sector", False),
}

SECTOR_ORDER = {s: i for i, s in enumerate(
    U.GROUPS["Financials"] + U.GROUPS["Commodities"])}

# Two lines per header, and a hairline before each new block. Twelve columns
# in three groups of four — where the contract sits in its own year, what it
# costs, and the levels those two came from — read as three tables the eye
# can take one at a time; the same twelve as an unbroken run read as a wall.
#
# The percentiles sit beside Last because they are the verdict: every other
# column is a level you have to already know the usual range of before it
# says anything, and these two are that range, already taken. They were last
# on the row, four columns of levels away from the name they belong to.
_H = [("", "Instrument", "l"), ("", "Last", ""),
      ("HV", "%", ""), ("ATR", "%", ""),
      ("Notional", "$", "sep"), ("Maint", "$", ""),
      ("", "Lev", ""), ("Days", "ATR", ""),
      ("HV", "20", "sep"), ("HV", "100", ""),
      ("ATR $", "20", ""), ("ATR $", "100", "")]


def _head(delta: bool = False) -> str:
    """Two lines per header cell, centred, on a shared top and bottom line.

    The qualifier was set at 9px on 0.65 opacity and read as damage rather
    than as hierarchy — at that size the eye cannot resolve whether HV/20 is
    two words or one smudged one.

    Centred rather than right-aligned to the figures: a two-line header hung
    off the right edge puts "HV" and "20" on different left margins whenever
    the words differ in width, so the stack reads as two stray labels instead
    of one.

    The one-word headers — Instrument, Last, Lev — take the top line and an
    empty second, so they sit level with Notional, Maint, Days, HV and ATR
    rather than sinking to the qualifier line. Every head-word on one line,
    every qualifier on the other. Emitting the blank line rather than
    aligning the cell to the top keeps the line boxes identical: a 10px
    qualifier and a 10.5px label do not land on the same pixel by themselves.
    """
    t = _tok()
    out = ""
    # The delta column only exists once there is an earlier day to subtract.
    # On a first run the header would otherwise promise a comparison the
    # payload cannot make and print nineteen dashes under it.
    cols = list(_H)
    if delta:
        cols.insert(6, ("Maint", "\u0394", ""))
    for top, bot, cls in cols:
        c = f' class="{cls}"' if cls else ""
        if top:
            l1 = (f'<span style="display:block;font-size:10px;font-weight:600;'
                  f'color:{t.get("body")};letter-spacing:.07em;'
                  f'margin-bottom:1px">{top}</span>')
            l2 = bot
        else:
            l1 = (f'<span style="display:block;font-size:10.5px;'
                  f'font-weight:600;color:{t.get("ink")};letter-spacing:.08em;'
                  f'margin-bottom:1px">{bot}</span>')
            l2 = "&nbsp;"
        out += (f'<th{c} style="color:{t.get("ink")};font-weight:600;'
                f'text-align:center;vertical-align:bottom">{l1}{l2}</th>')
    return out


def margins(d: dict, sort: str = "HV %ile") -> str:
    """One table, every contract, one ranking.

    Split into Financials and Commodities the sort ran twice and neither half
    knew about the other: picking "HV %ile" gave two local rankings and never
    answered which contract in the book is actually at an extreme, which is
    the only question the dropdown exists to ask. Nineteen rows is a short
    table. The sector swatch already carries the class the two eyebrows were
    spelling out, and the legend now names all eight sectors rather than the
    two groups, so the merge returns more than it takes. Sorting on Sector
    puts the old grouping back for the times you want it.

    The level columns — notional, maintenance, ATR $ — are not comparable
    across classes, and sorting the merged list on one of them clumps the
    rates and FX contracts at the top. That was half true inside Financials
    already (6J notional against NKD); the sorts actually reached for are the
    percentiles and leverage, and those are unit-free.

    Column order reads as one sentence: who it is and where it sits in its
    own year (last, HV %, ATR %), what it costs (notional, maintenance,
    leverage, days of ATR), and then the levels those came from (HV, ATR).
    Margin % and margin-over-vol are gone: leverage is the same fact as
    margin % inverted and in the unit the decision is actually made in, and
    margin-over-vol restated it against annualised vol while days-of-ATR
    already says it against the move the contract makes in a day. The
    z-scores are gone with them — the percentile ranks the same series
    against the same year and needs no explaining.
    """
    t = _tok()
    key, desc = MARGIN_SORTS.get(sort, MARGIN_SORTS["HV %ile"])
    flag = f'<div class="flag">{esc(d["warn"])}</div>' if d.get("warn") else ""
    since = d.get("prevDate")

    def dcell(v):
        # Blank, not a dash, when nothing moved. Fourteen of nineteen rows
        # hold still on a normal day and a column of dashes would bury the
        # five that did not. A dash still means "no earlier reading", which
        # is a different statement from "unchanged".
        if v is None:
            return '<td class="faint">—</td>'
        if not v:
            return "<td></td>"
        col = t.get("amber") if v > 0 else t.get("teal")
        return (f'<td style="color:{col}">{"+" if v > 0 else "−"}'
                f'{abs(v):,.0f}</td>')

    def pcell(p, sep=""):
        if p is None:
            return f'<td class="faint {sep}">—</td>'
        cls = "warn" if p >= 80 else "pos" if p <= 20 else "dim"
        return f'<td class="{cls} {sep}">{p:.0f}</td>'

    def scell(v, dec, cls=""):
        # cell() drops its class when the value is missing, which on a block
        # edge would take the hairline with it and leave a gap in the rule.
        n = num(v, dec)
        return (f'<td class="faint {cls}">—</td>' if n is None
                else f'<td class="{cls}">{n}</td>')

    def levcell(v):
        # Notional over maintenance, carrying its unit. "29.8x" is a sentence;
        # 3.35 in a column headed Marg % is a number you have to invert in
        # your head before it means anything.
        if v is None:
            return '<td class="faint">—</td>'
        return f'<td style="color:{t.get("ink")}">{v:,.1f}x</td>'

    # Leverage is computed here rather than in sk_margins: it is notional over
    # maintenance, both already on the row, and a copy keeps the cached
    # payload the data layer handed us untouched.
    rows = [dict(r, lev=(r["notional"] / r["maint"])
                 if (r.get("notional") and r.get("maint")) else None)
            for r in d.get("rows", [])]
    if not rows:
        return flag

    def order(r):
        if key == "sector":
            return (0, SECTOR_ORDER.get(r.get("sector"), 99),
                    -(r.get("volPct") or 0))
        v = r.get(key)
        return (v is None, -(v or 0) if desc else (v or 0), 0)

    rows.sort(key=order)

    body, seen = "", set()
    for r in rows:
        seen.add(r.get("sector", ""))
        vp = r.get("volPct")
        # The wash keys off HV, not ATR. They agree most of the time, and
        # tinting on both would give two rows the same colour for different
        # reasons — which is worse than tinting on one.
        tint = ""
        if vp is not None and vp >= 80:
            tint = f'background:{t.get("amber")}1a'
        elif vp is not None and vp <= 20:
            tint = f'background:{t.get("teal")}14'
        body += (f'<tr style="{tint}"><td class="l">'
                 f'{swatch(r.get("sector", ""))}{esc(r.get("code"))} '
                 f'<span class="nm">{esc(r.get("name"))}</span></td>'
                 # Last in the reading ink: it is the number every other
                 # column is derived from, so it should not be the faintest
                 # thing on the row.
                 f'<td style="color:{t.get("ink")}">'
                 f'{num(r.get("last"), r.get("dec", 2)) or "—"}</td>'
                 # The two percentiles adjacent, and both next to the name:
                 # one asks how wide the closes have been, the other how wide
                 # the days have been, and the pair only says something when
                 # they disagree.
                 + pcell(vp) + pcell(r.get("atrPct"))
                 + scell(r.get("notional"), 0, "dim sep")
                 # Maintenance in the reading ink alongside last: it is the
                 # cash the contract actually ties up, and dimming it put the
                 # one number a size decision starts from behind the
                 # statistics derived from it.
                 + f'<td style="color:{t.get("ink")}">'
                   f'{num(r.get("maint"), 0) or "—"}</td>'
                 + (dcell(r.get("maintChg")) if since else "")
                 + levcell(r.get("lev")) + cell(r.get("daysATR"), 1)
                 + scell(r.get("annVol"), 1, "sep")
                 + cell(r.get("vol100"), 1, "dim")
                 + cell(r.get("atr"), 0) + cell(r.get("atr100"), 0, "dim")
                 + "</tr>")

    # Legend in universe order, not sort order: the key is a map of the book
    # and should not reshuffle every time the ranking column changes.
    legend = "".join(
        f'<span class="key">{swatch(s)}{esc(s)}</span>'
        for g in ("Financials", "Commodities") for s in U.GROUPS[g]
        if s in seen)
    # The label carries the date it actually compared against, not the word
    # "yesterday". The terminal is not opened every day, and a four-day gap
    # that says yesterday is worse than no column at all.
    when = ""
    if since:
        try:
            when = " · maint vs " + dt.date.fromisoformat(since).strftime(
                "%-d %b" if os.name != "nt" else "%#d %b")
        except ValueError:
            when = ""
    return (flag
            + eyebrow(f"{len(rows)} contracts{when}",
                      f'<span class="legend">{legend}</span>')
            + table(_head(bool(since)), body))


# ------------------------------------------------- Volatility across bars
# The bar list is sk_margins' — it decides which frames get computed, and a
# second copy here would be a grid that silently disagreed with its own data.
MG_BARS = MG.VOL_BARS
TF_LABEL = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D", "1wk": "1W"}

# Rank on any one column, or group by sector. No level sorts here — every
# figure in the table is already a rank, so there is nothing else to rank on.
VOL_GRID_SORTS = {f"{m.upper() if m == 'atr' else 'HV'} {TF_LABEL[tf]}":
                  (m, tf) for m in ("hv", "atr") for tf in MG_BARS}
VOL_GRID_SORTS["Sector"] = ("sector", "")

# One block per bar, HV and ATR paired inside it. Split into a block of HV
# and a block of ATR, the two readings for the same bar sat five columns
# apart and the comparison they exist to support — closes wide, days narrow,
# or the reverse — had to be carried across the table by eye. The timeframe
# takes the top line and names the block; the measure takes the bottom line.
_VH = ([("", "Instrument", "l")]
       + [(TF_LABEL[tf], m, "tfsep" if i == 0 else "")
          for tf in MG_BARS for i, m in enumerate(("HV", "ATR"))])


def _vhead() -> str:
    t = _tok()
    out = ""
    for top, bot, cls in _VH:
        c = f' class="{cls}"' if cls else ""
        if top:
            l1 = (f'<span style="display:block;font-size:10px;font-weight:600;'
                  f'color:{t.get("body")};letter-spacing:.07em;'
                  f'margin-bottom:1px">{top}</span>')
            l2 = bot
        else:
            l1 = (f'<span style="display:block;font-size:10.5px;'
                  f'font-weight:600;color:{t.get("ink")};letter-spacing:.08em;'
                  f'margin-bottom:1px">{bot}</span>')
            l2 = "&nbsp;"
        out += (f'<th{c} style="color:{t.get("ink")};font-weight:600;'
                f'text-align:center;vertical-align:bottom">{l1}{l2}</th>')
    return out


def vol_grid(d: dict, sort: str = "HV 1D") -> str:
    """The same nineteen rows, read at four bar sizes.

    The margin table answers "is this expensive for what it moves" one
    contract at a time. This one answers "what is moving, and since when",
    which is the question the margin table was being used for sideways. Every
    cell is a percentile of that contract against its own history at that bar
    size, so the whole grid is on one scale and the row reads left to right
    from the day into the session: hot at 15m and cold at 1D is something
    that started this morning, cold at 15m and hot at 1D is something
    burning out.

    No row wash here, unlike the margin table. Eight tinted cells a row
    already make a heat map, and a background behind them would be a second
    signal competing with the one the reader is meant to scan.
    """
    t = _tok()
    rows = list(d.get("rows") or [])
    if not rows:
        return ""
    meas, tf = VOL_GRID_SORTS.get(sort, VOL_GRID_SORTS["HV 1D"])

    def order(r):
        if meas == "sector":
            return (0, SECTOR_ORDER.get(r.get("sector"), 99),
                    -(r["hv"].get("1d") or 0))
        v = r.get(meas, {}).get(tf)
        return (v is None, -(v or 0), 0)

    rows.sort(key=order)

    def pcell(p, sep=""):
        if p is None:
            return f'<td class="faint {sep}">—</td>'
        cls = "warn" if p >= 80 else "pos" if p <= 20 else "dim"
        return f'<td class="{cls} {sep}">{p:.0f}</td>'

    body = ""
    for r in rows:
        body += (f'<tr><td class="l">{swatch(r.get("sector", ""))}'
                 f'{esc(r.get("code"))} '
                 f'<span class="nm">{esc(r.get("name"))}</span></td>')
        for b in MG_BARS:
            for i, m in enumerate(("hv", "atr")):
                body += pcell(r.get(m, {}).get(b), "tfsep" if i == 0 else "")
        body += "</tr>"

    warn = f'<div class="flag">{esc(d["warn"])}</div>' if d.get("warn") else ""
    return (warn
            + eyebrow("Volatility percentile by bar",
                      '<span class="legend"><span class="key">20 bars of '
                      'lookback at every size</span></span>')
            + table(_vhead(), body))


# ------------------------------------------------ Volatility levels by bar
# Same eight columns as the percentile grid, carrying the figures the ranks
# were taken of. The two tables answer different halves of one question: the
# grid says whether a contract is unusual for itself, this one says how much
# it actually moves, and neither is recoverable from the other.
VOL_LEVEL_SORTS = {f"{'ATR' if m == 'atrLvl' else 'HV'} {TF_LABEL[tf]}":
                   (m, tf) for m in ("hvLvl", "atrLvl") for tf in MG_BARS}
VOL_LEVEL_SORTS["Sector"] = ("sector", "")

_LH = ([("", "Instrument", "l")]
       + [(TF_LABEL[tf], m, "tfsep" if i == 0 else "")
          for tf in MG_BARS for i, m in enumerate(("HV %", "ATR $"))])


def _lhead() -> str:
    t = _tok()
    out = ""
    for top, bot, cls in _LH:
        c = f' class="{cls}"' if cls else ""
        if top:
            l1 = (f'<span style="display:block;font-size:10px;font-weight:600;'
                  f'color:{t.get("body")};letter-spacing:.07em;'
                  f'margin-bottom:1px">{top}</span>')
            l2 = bot
        else:
            l1 = (f'<span style="display:block;font-size:10.5px;'
                  f'font-weight:600;color:{t.get("ink")};letter-spacing:.08em;'
                  f'margin-bottom:1px">{bot}</span>')
            l2 = "&nbsp;"
        out += (f'<th{c} style="color:{t.get("ink")};font-weight:600;'
                f'text-align:center;vertical-align:bottom">{l1}{l2}</th>')
    return out


def vol_levels(d: dict, sort: str = "HV 1D") -> str:
    """The figures behind the percentiles, same eight columns.

    Annualised vol is on one scale across the row, which is the point of
    annualising: 15m at 2.4% beside 1D at 12.6% says the last five hours have
    been far calmer than a normal day for that contract, and the rank grid
    can only imply it. ATR is in dollars for the same reason it is on the
    margin table — a 0.5 move in NG and a 5-point move in ES are incomparable
    until the multiplier is applied.

    No tint. The grid above is the heat map and this is its footnote; two
    heat maps stacked would leave the reader deciding which one to scan.
    """
    t = _tok()
    rows = list(d.get("rows") or [])
    if not rows:
        return ""
    meas, tf = VOL_LEVEL_SORTS.get(sort, VOL_LEVEL_SORTS["HV 1D"])

    def order(r):
        if meas == "sector":
            return (0, SECTOR_ORDER.get(r.get("sector"), 99),
                    -(r["hvLvl"].get("1d") or 0))
        v = r.get(meas, {}).get(tf)
        return (v is None, -(v or 0), 0)

    rows.sort(key=order)

    def lcell(v, dec, cls, sep=""):
        if v is None:
            return f'<td class="faint {sep}">—</td>'
        return f'<td class="{cls} {sep}">{v:,.{dec}f}</td>'

    body = ""
    for r in rows:
        body += (f'<tr><td class="l">{swatch(r.get("sector", ""))}'
                 f'{esc(r.get("code"))} '
                 f'<span class="nm">{esc(r.get("name"))}</span></td>')
        for b in MG_BARS:
            # Vol in the reading ink, ATR dimmed behind it: the pair is one
            # fact stated twice, once as a rate and once as cash, and giving
            # both equal weight made the row read as eight separate numbers.
            body += lcell(r.get("hvLvl", {}).get(b), 1, "dim", "tfsep")
            body += lcell(r.get("atrLvl", {}).get(b), 0, "dim")
        body += "</tr>"

    return (eyebrow("Volatility levels by bar",
                    '<span class="legend"><span class="key">annualised %, '
                    'and ATR in dollars</span></span>')
            + table(_lhead(), body))


# --------------------------------------------------------------- Calendar
TYPE_COL = {"Policy": "#a596d6", "Macro": "#6f9fd8", "Inventory": "#c08360",
            "Report": "#a5b96f", "Positioning": "#d0ae6b",
            "Holiday": "#8b979f", "Contract": "#5fb8ac"}


def _syms(codes, limit=6) -> str:
    if not codes:
        return '<span class="faint">—</span>'
    if len(codes) >= len(U.CODES):
        return '<span class="lg">ALL</span>'
    shown = " ".join(codes[:limit])
    more = (f' <span class="faint">+{len(codes) - limit}</span>'
            if len(codes) > limit else "")
    return shown + more


def calendar(rows, horizon_days: int, warn=None) -> str:
    """One table. Today is the first section rather than a separate card, so
    the eye runs straight from what happens in the next few hours into the
    weeks behind it without changing format halfway down."""
    t = _tok()
    today_d = dt.date.today()

    head = ('<th class="l">Date</th><th class="l">Symbol</th>'
            '<th class="l">Time</th><th class="l">Event</th>'
            '<th class="l">Countdown</th><th class="l">Type</th>')

    def section(label, accent=False):
        col = t.get("teal") if accent else t.get("faint")
        return (f'<tr class="sec"><td class="l" style="color:{col};'
                f'font-weight:650;letter-spacing:.09em;'
                f'text-transform:uppercase;font-size:10.5px">{esc(label)}</td>'
                f'<td colspan="5"></td></tr>')

    def row(r, tint=""):
        col = TYPE_COL.get(r["type"], t.get("mute"))
        # Two things earn a wash across the row: today, and a market holiday.
        # Both change the context you are reading in rather than being louder
        # events. Everything else is distinguished by its Type dot.
        holiday = r["type"] == "Holiday"
        region = r.get("region", "")
        if holiday:
            hc = {"US": t.get("amber"),
                  "US-B": t.get("sec-bonds", t.get("mute")),
                  "SG": t.get("sec-currencies", t.get("mute"))}.get(
                      region, t.get("mute"))
            return (
                f'<tr style="background:{hc}1f">'
                f'<td class="l">{esc(r["date"].strftime("%a %d %b"))}</td>'
                f'<td class="l" style="color:{hc};letter-spacing:.06em">'
                f'{region}</td>'
                f'<td class="l faint">all day</td>'
                f'<td class="l">{esc(r["event"])}</td>'
                f'<td class="l dim">{r["when"]}</td>'
                f'<td class="l"><i class="sw" style="background:{hc}"></i>'
                f'Holiday</td></tr>')

        # Colour marks importance, not proximity. Highlighting everything
        # inside a week lit the whole first block, and a highlight that
        # applies to every row is decoration. Countdown and the week rules
        # already say how far away a thing is.
        e_style = (f'color:{t.get("teal")};font-weight:600'
                   if r.get("high") else "")
        time = (f'{r["time_sg"]} <span class="faint">SGT</span>'
                f'<span class="faint" style="margin-left:9px;opacity:.7">'
                f'{r["time_et"]} ET</span>')
        return (
            f'<tr style="{tint}"><td class="l">'
            f'{"" if r["exact"] else "≈ "}'
            f'{esc(r["date"].strftime("%a %d %b"))}</td>'
            f'<td class="l faint">{_syms(r["symbols"])}</td>'
            f'<td class="l dim">{time}</td>'
            f'<td class="l" style="{e_style}">{esc(r["event"])}</td>'
            f'<td class="l dim">{r["when"]}</td>'
            f'<td class="l"><i class="sw" style="background:{col}"></i>'
            f'{esc(r["type"])}</td></tr>')

    # Today is a row, not a banner. It sits on a teal wash so it reads as
    # "you are here" without breaking the table into two formats — the same
    # trick the holiday rows use, for the same reason.
    tint = f'background:{t.get("teal")}1a'
    today_rows = [r for r in rows if r["days"] == 0]
    if today_rows:
        body = "".join(row(r, tint) for r in today_rows)
    else:
        body = (f'<tr style="{tint}">'
                f'<td class="l" style="color:{t.get("teal")};font-weight:600">'
                f'{esc(today_d.strftime("%a %d %b"))}</td>'
                f'<td class="l faint">—</td><td class="l faint">—</td>'
                f'<td class="l faint">Nothing scheduled</td>'
                f'<td class="l dim">today</td><td class="l faint">—</td></tr>')

    last_week = None
    for r in rows:
        if r["days"] == 0:
            continue
        # Key on (year, week) and label with that week's MONDAY. Keying on the
        # week number alone would collide across a year boundary, and labelling
        # from the first row printed "Week of 19 Aug" — a Wednesday — whenever
        # the earlier days of the week had already gone into the today block.
        iso = r["date"].isocalendar()
        wk = (iso[0], iso[1])
        if wk != last_week:
            last_week = wk
            monday = r["date"] - dt.timedelta(days=r["date"].weekday())
            body += section(f'Week of {monday.strftime("%d %b")}')
        body += row(r)

    flag = ""
    if warn:
        flag = (f'<div class="flag">Hand-maintained schedule exhausted for '
                f'{", ".join(warn)} — those rows will stop appearing until '
                f'the dates are extended in sk_calendar.py.</div>')

    return flag + table(head, body)


# -------------------------------------------------------------- Knowledge
def contracts_table(last: dict = None) -> str:
    """What you actually trade: multiplier, live notional, and the small
    contract where one exists.

    Notional is carried because a multiplier alone does not tell you the size
    of the thing — 6J's 12,500,000 and ZC's 50 are unreadable side by side
    until both are priced, and it is the notional that decides how many
    contracts balance a spread.
    """
    t = _tok()
    last = last or {}
    ink = t.get("ink", "#0d1418")
    head = ('<th class="l">Instrument</th><th>Last</th><th>Multiplier</th>'
            '<th>Notional</th><th>Fee</th><th>bp</th>'
            '<th class="l">Small</th><th>Multiplier</th>'
            '<th>Notional</th><th>Fee</th><th>bp</th><th>Fraction</th>')
    body = ""
    for c in U.CODES:
        m, mic, px = U.MULT.get(c), U.MICRO.get(c), last.get(c)
        fee_std, fee_sml = U.FEES.get(c, (None, None))
        notl = px * m if (px and m) else None
        mnotl = px * mic[1] if (mic and px) else None

        # Commission as basis points of the contract's own notional, which is
        # the only form in which ES and ZC are comparable: $4 on a $390k index
        # future is a tenth of a basis point, the same $4.40 on a $30k corn
        # contract is one and a half. It is also the number that says why a
        # micro is expensive — same fee per dollar as its standard, roughly
        # doubled, because the fee falls by a fifth while the notional falls
        # by a tenth.
        def bp(fee, size):
            return (f'{fee / size * 10_000:,.2f}'
                    if (fee and size) else "—")

        body += (f'<tr><td class="l">{swatch(U.SECTOR[c])}{esc(c)} '
                 f'<span class="nm">{esc(U.NAME[c])}</span></td>'
                 + cell(px, U.DEC.get(c, 2), "dim")
                 + cell(m, 0, "dim")
                 + f'<td style="color:{ink};font-weight:600">'
                 + (f'{notl:,.0f}' if notl else "—") + "</td>"
                 + cell(fee_std, 2, "dim")
                 + f'<td class="dim">{bp(fee_std, notl)}</td>'
                 + (f'<td class="l" style="color:{ink}">{esc(mic[0])}</td>'
                    + cell(mic[1], 0, "dim")
                    + cell(mnotl, 0, "dim")
                    + cell(fee_sml, 2, "dim")
                    + f'<td class="dim">{bp(fee_sml, mnotl)}</td>'
                    + f'<td class="dim">1/{mic[2]}</td>'
                    if mic else
                    '<td class="l faint">—</td><td class="faint">—</td>'
                    '<td class="faint">—</td><td class="faint">—</td>'
                    '<td class="faint">—</td><td class="faint">—</td>')
                 + "</tr>")
    return (eyebrow("Contract specifications")
            + note("Notional = last × multiplier, priced off the same daily "
                   "closes as the Board. The small contract is what makes a "
                   "computed ratio executable — a 1.6 : 1 spread is 8 : 1 in "
                   "micros. <b>Fee</b> is one round turn, all in, and "
                   "<b>bp</b> is that fee against the contract&#39;s own "
                   "notional: the column that says a micro costs about twice "
                   "as much per dollar of exposure as its standard, and that "
                   "a corn contract costs ten times what an index one does. "
                   "Specifications and fees are transcribed, not fetched, and "
                   "commission is the negotiable half: <b>check both against "
                   "CME and your broker before trading off them</b>.",
                   wide=True)
            + table(head, body))


def knowledge(group: str = "All", last: dict = None) -> str:
    cards = ""
    for code in U.CODES:
        sec = U.SECTOR[code]
        if group != "All" and U.GROUP_OF[sec] != group:
            continue
        ds = KN.KNOWLEDGE.get(code, [])
        if not ds:
            continue
        items = "".join(f"<li><b>{esc(t)}</b><span>{esc(dsc)}</span></li>"
                        for t, dsc in ds)
        cards += (f'<div class="dcard"><div class="dhead">{swatch(sec)}'
                  f'<b>{esc(code)}</b> {esc(U.NAME[code])}'
                  f'<span class="dsec">{esc(sec)}</span></div>'
                  f'<ol class="dlist">{items}</ol></div>')
    return (contracts_table(last)
            + note("What actually moves each contract, ordered by how often it "
                 "sets the tone rather than by how much it can move on its day. "
                 "Maintained by hand — a driver you cannot sign is a topic, "
                 "not a driver.")
            + f'<div class="dgrid">{cards}</div>')


# ------------------------------------------------------------------- News
def news(markets: dict, warn: str = "") -> str:
    """Fetched server-side now rather than through a CORS proxy in the browser.
    That removes the one tab that depended on a third party neither we nor the
    exchange controls."""
    flag = f'<div class="flag">{esc(warn)}</div>' if warn else ""
    if not markets:
        return (flag + '<div class="skel">No commentary came back — Trading '
                "Economics may be refusing this host. Try Refresh.</div>")
    t = _tok()
    cols = ""
    for group, secs in U.GROUPS.items():
        items = ""
        for code in U.CODES:
            if U.GROUP_OF[U.SECTOR[code]] != group:
                continue
            m = markets.get(code)
            if not m:
                continue
            # Date and source are a footer, not a trailing sentence. Pushed to
            # opposite ends of a hairline row so neither reads as part of the
            # blurb. Styled inline because Streamlit's own link rule outranks
            # a class selector here.
            src = U.TE_PAGE.get(code, "")
            link = (f'<a href="{esc(src)}" target="_blank" rel="noopener" '
                    f'style="color:{t.get("teal", "#0d8f83")};text-decoration:none;'
                    f'font-size:11px">source ↗</a>' if src else "")
            # The headline is shown because the blurb is whatever paragraph sits
            # under it, and TE's market pages lead with a related-but-different
            # story often enough that the reader needs to see what they are
            # reading about. Off-topic is marked rather than hidden.
            hl = esc(m.get("headline") or "")
            off = ("" if m.get("onTopic", True) else
                   f'<span style="color:{t.get("amber", "#96701c")};'
                   f'font-size:10.5px;'
                   f'letter-spacing:.06em"> · not {esc(code)}-specific</span>')
            items += (
                f'<div class="mkt"><h6>{esc(code)}  {esc(U.NAME[code])}</h6>'
                + (f'<div style="font-size:11.5px;color:{t.get("body", "#3a464e")};'
                   f'font-weight:600;margin:-4px 0 6px">{hl}{off}</div>'
                   if hl else "")
                + f'<p>{esc(m["blurb"])}</p>'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:baseline;margin-top:10px;padding-top:8px;'
                f'border-top:1px solid {t.get("line", "#e0e5e8")}">'
                f'<span style="font-size:11px;color:{t.get("faint", "#97a2ab")}">'
                f'{esc(m.get("date") or "")}</span>{link}</div></div>')
        if items:
            cols += (f'<div>{eyebrow(group)}<div class="card">{items}</div>'
                     f"</div>")
    return flag + f'<div class="grid2 news">{cols}</div>'
