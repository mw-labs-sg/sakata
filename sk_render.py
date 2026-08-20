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

import sk_charts as CH
import sk_knowledge as KN
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

    return (f'<div class="bar"><span class="spacer"></span>'
            f'<span class="chip">{len(d["rows"])} instruments</span></div>'
            + eyebrow(f"Sector performance · {hz} %")
            + f'<div class="plot">{CH.bar_chart(agg)}</div>'
            + '<div class="grid2" style="margin-top:16px">'
            + panel("Financials") + panel("Commodities") + "</div>")


# -------------------------------------------------------------- Technical
def technical(d: dict, code: str, hz: str, dec: int) -> str:
    order, grid = d["order"], d["grid"]
    head = ('<th class="l">Instrument</th>' +
            "".join(f"<th>{h}</th>" for h in order) + "<th>Σ</th>")
    body, last_sec = "", None
    for u_code in U.CODES:
        g = grid.get(u_code)
        if not g:
            continue
        sec = U.SECTOR[u_code]
        if sec != last_sec:
            last_sec = sec
            body += (f'<tr class="sec"><td class="l">{esc(sec)}</td>'
                     f'<td colspan="{len(order) + 1}"></td></tr>')
        tot, cells = 0, ""
        for h in order:
            c = g.get(h)
            if not c:
                cells += '<td class="faint">—</td>'
                continue
            tot += c["score"]
            title = f'{c["bias"]} · {c["regime"]} / {c["retrace"]} / {c["trend"]}'
            cells += (f'<td style="color:{BIAS_COL[str(c["score"])]};'
                      f'font-weight:600" title="{esc(title)}">'
                      f'{"+" if c["score"] > 0 else ""}{c["score"]}</td>')
        body += (f'<tr><td class="l ind">{esc(u_code)} '
                 f'{esc(U.NAME[u_code])}</td>{cells}'
                 f'<td style="color:{C["pos"] if tot >= 0 else C["amber"]};'
                 f'font-weight:600">{"+" if tot > 0 else ""}{tot}</td></tr>')

    g = grid.get(code, {})
    c = g.get(hz, {})
    chart = ('<div class="skel">no series</div>' if not c.get("t") else
             CH.candles(c["t"], c["o"], c["h"], c["l"], c["c"], [
                 {"k": "PH", "v": c["ph"], "c": C["down"], "dash": "4 3"},
                 {"k": "PL", "v": c["pl"], "c": C["up"], "dash": "4 3"},
                 {"k": "Mid", "v": c["md"], "c": C["faint"], "dash": "2 4"},
                 {"k": "RB", "v": c["vb"], "c": C["deep"]},
                 {"k": "RS", "v": c["vs"], "c": C["amber"]},
             ], h=300, dec=dec))

    lv = "".join(
        f'<tr><td class="l">{k}</td>{cell(v, dec)}</tr>' for k, v in [
            ("Prior high", c.get("high")), ("RS target", c.get("rs")),
            ("Mid", c.get("mid")), ("RB stop", c.get("rb")),
            ("Prior low", c.get("low")), ("Close", c.get("close")),
            ("MA100", c.get("ma100")), ("MA200", c.get("ma200"))])

    pos = "—" if c.get("pos") is None else f'{num(c["pos"], 0)}%'
    rr = "—" if c.get("rr_retrace") is None else num(c["rr_retrace"], 2)
    return (note("Range Levels: prior-segment high/low with the RB/RS retrace "
                 "bands. Each horizon votes <b>range</b>, <b>retrace</b> and "
                 "<b>trend</b>, summing to a bias between −3 and +3. Σ is the "
                 "ladder total.")
            + eyebrow("Bias matrix") + table(head, body)
            + note(f'<b>{esc(code)} · {esc(hz)}</b> — {esc(c.get("bias", "—"))} '
                   f'({esc(c.get("regime", "—"))} / {esc(c.get("retrace", "—"))} '
                   f'/ {esc(c.get("trend", "—"))}) · position {pos} of prior '
                   f'range · R:R to band {rr}')
            + f'<div class="plot">{chart}</div>'
            + eyebrow("Levels")
            + table('<th class="l">Level</th><th>Price</th>', lv))


# ---------------------------------------------------------------- Spreads
def _pad(s, n):
    s = str(s)
    return s + " " * max(n - len(s), 0)


def _rpad(s, n):
    s = str(s)
    return " " * max(n - len(s), 0) + s


def _fx(v, d):
    return "-" if v is None else f"{float(v):.{d}f}"


def _sfx(v, d):
    return "-" if v is None else f'{"+" if v >= 0 else ""}{float(v):.{d}f}'


def digest(p: dict, generated: str = "") -> str:
    L = [f'SAKATA · {p["window"]} · {p["note"]}',
         f"generated    {generated} UTC",
         f'window       {p["window"]}, {p["start"]} to {p["end"]} '
         f'({p["span"]} calendar days)',
         f'sample       {p["bars"]} bars, {p["instruments"]} instruments, '
         f'annualised x{p["ann"]}',
         f'Sharpe SE    +/-{p["se"]} over this span',
         f'field        {p["nOut"]} outrights + {p["nPair"]} pairs' +
         (f', {p["nCapped"]} hidden by the 5:1 leg cap' if p["nCapped"] else ""),
         f'medians      pair Sharpe {p["medPair"]} vs outright {p["medOut"]}'
         f"   <- like-for-like",
         f'noise floor  expected best-of-{p["nField"]} Sharpe from pure noise '
         f'~{round(p["noise"])}. Treat anything below that as unproven.', "",
         "ranked on ER = Kaufman efficiency: |net move| / path length.",
         "ER (Adj) = ER * sqrt(bars), for comparing ACROSS windows only.",
         "vs leg   = spread ER against the better leg held alone, per cent.", "",
         _pad("#", 3) + " " + _pad("LONG", 6) + _pad("SHORT", 6) +
         _pad("SECTOR", 9) + _rpad("ER", 7) + _rpad("ERADJ", 7) +
         _rpad("SHRP", 7) + _rpad("WIN%", 6) + _rpad("TOT%", 8) +
         _rpad("VOL%", 7) + _rpad("MDD%", 7) + _rpad("VSLEG", 7)]
    for r in p["rows"]:
        L.append(_rpad(r["n"], 3) + " " + _pad(r["long"] or "cash", 6) +
                 _pad(r["short"] or "cash", 6) +
                 _pad(str(r["sector"])[:8], 9) +
                 _rpad(_fx(r["er"], 3), 7) + _rpad(_fx(r.get("erAdj"), 2), 7) +
                 _rpad(_fx(r["sharpe"], 2), 7) + _rpad(_fx(r["win"], 0), 6) +
                 _rpad(_sfx(r["tot"], 2), 8) + _rpad(_fx(r["vol"], 1), 7) +
                 _rpad(_fx(r["mdd"], 2), 7) +
                 _rpad(_sfx(r.get("legDelta"), 0), 7))
    L += ["", "leg concentration in the top 20 — one ticker dominating the "
              "short", "column means the field is one macro bet replicated",
          "  short: " + "  ".join(f"{a}x{b}" for a, b in p["legShort"]),
          "  long:  " + "  ".join(f"{a}x{b}" for a, b in p["legLong"])]
    if p.get("dropped"):
        L += ["", "dropped for thin coverage: " + ", ".join(p["dropped"])]
    return "\n".join(L)


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
            + note("ER (Adj) = ER &#215; &#8730;bars. Raw ER decays as "
                   "1/&#8730;n, so the adjusted figure is the one that "
                   "compares across windows — 1.0 is the noise floor. ROA is "
                   "the same window's return over its worst drawdown.")
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
def portfolio(res: dict, per: str, fresh: str = "") -> str:
    """Optimised weights, what they scored, and the curve they scored it on.

    Two blocks and a picture: the weights themselves, then the same statistics
    the Trends table carries, quoted twice — the searched weights against equal
    weight over the SAME legs. That comparison is the point of the second row.
    A search that cannot beat naive weighting on its own objective has found a
    way to spend a click, and the only way to see that is side by side.
    """
    if not res or not res.get("weights"):
        return ('<div class="skel">No portfolio yet — set the objective and '
                "press Optimise.</div>")
    t = _tok()
    ink = t.get("ink", "#0d1418")
    teal, amber = t.get("teal", "#0d8f83"), t.get("amber", "#96701c")
    faint = t.get("faint", "#97a2ab")
    st_, eq = res["stats"], res["equal"]

    # Weight as a bar as well as a number: the sizes are the whole output, and
    # a column of percentages makes the reader do the comparing.
    top = max(abs(w["w"]) for w in res["weights"]) or 1
    rows = ""
    for i, w in enumerate(res["weights"], 1):
        long_ = w["w"] >= 0
        col = teal if long_ else amber
        code = w["code"]
        name = U.NAME.get(code, "")
        bar = (f'<span style="display:inline-block;height:8px;border-radius:2px;'
               f'background:{col};width:{abs(w["w"]) / top * 84:.0f}px;'
               f'vertical-align:middle"></span>')
        rows += (f'<tr><td class="l faint">{i}</td>'
                 f'<td class="l">{swatch(U.SECTOR.get(code, ""))}{esc(code)} '
                 f'<span class="nm">{esc(name)}</span></td>'
                 f'<td class="l" style="color:{col};font-weight:600">'
                 f'{"long" if long_ else "short"}</td>'
                 f'<td style="color:{ink};font-weight:700">{abs(w["w"]):.1f}%</td>'
                 f'<td class="l">{bar}</td></tr>')

    def statrow(label, d, strong):
        cells = "".join(
            f'<td style="color:{col or ink};'
            f'font-weight:{700 if strong else 600}">{v}</td>'
            for v, col in (
                (num(d.get("erAdj"), 2), None), (num(d.get("roa"), 1), None),
                (num(d.get("sharpe"), 2), None), (f'{d.get("win", 0):.0f}',
                                                  None),
                (num(d.get("vol"), 1), None),
                (f'{"+" if (d.get("tot") or 0) >= 0 else ""}'
                 f'{num(d.get("tot"), 1)}',
                 t.get("pos", "#0a7c66") if (d.get("tot") or 0) >= 0 else amber),
                (num(d.get("mdd"), 1), amber)))
        return f'<tr><td class="l">{esc(label)}</td>{cells}</tr>'

    curve, eqc = res["curve"], res["equalCurve"]
    series = [{"k": "equal weight", "v": eqc["v"], "c": faint, "w": 1.4,
               "dash": "4 3", "o": 0.9},
              {"k": "optimised", "v": curve["v"], "c": ink, "w": 2.6}]

    return (eyebrow(f"Portfolio Weights — {esc(res['objective'])}, {esc(per)}")
            + note("Weights are gross: they sum to 100% of the risk budget, "
                   "with shorts carrying the same weight as longs. Searched, "
                   "not solved — ROA and ER depend on the order of the "
                   "returns, so there is no covariance matrix to invert and "
                   "no proof this is the global best. Fitted on this window "
                   "with no holdout, so read the equal-weight row as the bar "
                   "it had to clear.")
            + table('<th class="l">#</th><th class="l">Instrument</th>'
                    '<th class="l">Side</th><th>Weight</th><th class="l"></th>',
                    rows)
            + eyebrow("What those weights scored")
            + table('<th class="l"></th><th>ER (Adj)</th><th>ROA</th>'
                    '<th>Sharpe</th><th>Win%</th><th>Vol%</th><th>Tot%</th>'
                    '<th>MDD%</th>',
                    statrow("Optimised", st_, True)
                    + statrow("Equal weight, same legs", eq, False))
            + chips([f'{res["legs"]} legs', f'{res["bars"]} bars',
                     f'drawdown on {res["fineBars"]:,} marks',
                     f'net {res["net"]:+.0f}% of gross']
                    + ([fresh] if fresh else []))
            + '<div class="plot" style="margin-top:10px">'
            + CH.line_chart(curve["t"], series, None, 1100, 300, 1)
            + "</div>")


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
            fresh: str = "") -> str:
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
            f'<th class="l">Ratio ({esc(weighting["label"])})</th>'
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
        # A count, not a list of names. The names are still there on hover for
        # the one row in twenty where you want to know which.
        # Contracts per leg for equal dollar risk, long : short. Not the sigma
        # ratio — a 6J contract carries $78k of notional against $24k for ZC,
        # so matching volatility is not matching size.
        # The order, not the ratio. 1.6 : 1 cannot be sent anywhere; the
        # whole-contract equivalent can, and micros are what make it reachable.
        # The ratio it targets, how far off the hedge lands and what one unit
        # costs all sit on hover rather than widening the row.
        # One unit of the long leg against however much of the short it takes.
        # The whole-contract combinations that used to sit here — full size and
        # smallest micro equivalent — were two more decisions in a cell that
        # only has to answer "how much of the other one". They survive on
        # hover, for when the order is actually being filled.
        ex = r.get(sxkey)
        if ex:
            qty = 1 / ex          # short legs per single long leg
            tk = (r.get("ticket") or {}).get("std") or {}
            tip = (f'whole contracts: {tk["text"]} ({tk["err"]}% off, '
                   f'${tk.get("risk", 0):,.0f} risk)' if tk.get("text") else "")
            size = (f'<td class="l dim" title="{esc(tip)}">'
                    f'1 {esc(r["long"])} : {qty:,.2f} {esc(r["short"])}</td>')
        else:
            size = '<td class="l faint">—</td>'
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
            + note("ROA is return over maximum drawdown: Tot% divided by the "
                   "worst hole it took, unannualised, so 10 means it made ten "
                   "times what that hole cost — measured on the finest marks "
                   "the window reaches back over, not on its own bar, so a "
                   "daily window cannot step over an intraday trough. "
                   "Ratio is how much of the short leg "
                   "one long leg needs; hover for a whole-contract fill. "
                   "Sizing: "
                   + ("matching dollar risk, n × notional × σ."
                      if d.get("mode") == "vol" else
                      "matching dollar exposure, n × notional, ignoring vol.")
                   + " vs leg is the spread's ER against the better of its two "
                     "legs held alone; negative means it did not pay for itself. "
                     "Top 10 counts the other windows it also ranks in.")
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
            + spread_charts(p, t, sort))


def spread_charts(p: dict, t: dict = None,
                  sort: str = DEFAULT_SORT) -> str:
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
        cards += (f'<div class="plot"><div class="ctitle">'
                  f'<b>{n}. {esc(c["label"])}</b>'
                  # The verdict was already reaching for the far corner with
                  # margin-left:auto; on the title row it gets one, and the
                  # name has the row to itself now that its number moved down
                  # into the stat line with the rest of them.
                  f'{verdict}</div>'
                  f'<div class="clegend">{legend}</div>'
                  f'<div class="cstats">{stats}</div>'
                  + CH.line_chart(c["t"], series, None, 560, 220, 1) + "</div>")
    return (eyebrow("Why they ranked")
            + note("Legs rebased to 100 — turquoise long, orange short — so "
                   "they sit at equal notional. "
                   + ("The spread over them is <b>vol-adjusted</b>, so it is "
                      "not the gap between the two lines."
                      if mode == "vol" else
                      "The spread over them is <b>equal-notional</b>, which is "
                      "the gap between the two lines.")
                   + f" The table's top twelve on {esc(sort)}, in its"
                     " order — card 3 is row 3.")
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
MARGIN_SORTS = {
    "RV %ile": ("volPct", True),
    "RV z": ("volZ", True),
    "ATR %ile": ("atrPct", True),
    "ATR z": ("atrZ", True),
    "RSI": ("rsi", True),
    "Marg/Vol": ("margVol", False),
    "Days ATR": ("daysATR", False),
    "RV 20d": ("annVol", True),
    "ATR $": ("atr", True),
    "Margin %": ("marginPct", True),
    "Notional": ("notional", True),
}

# Two lines per header. Sixteen columns of one-line labels forces the table
# wider than the page; stacking the qualifier under the measure buys the width
# back without abbreviating anything into guesswork.
_H = [("", "Instrument", "l"), ("", "Last", ""),
      ("RV", "20d", ""), ("RV", "100d", ""), ("RV", "%ile", ""),
      ("RV", "z", ""),
      ("ATR $", "20d", ""), ("ATR $", "100d", ""), ("ATR", "%ile", ""),
      ("ATR", "z", ""),
      ("RSI", "14d", ""),
      ("Marg", "/Vol", ""), ("Days", "ATR", ""),
      ("Marg", "%", ""), ("Maint", "$", ""), ("Notional", "$", "")]


def _head() -> str:
    """Two lines per header cell, both in the reading ink.

    The qualifier was set at 9px on 0.65 opacity and read as damage rather
    than as hierarchy — at that size the eye cannot resolve whether RV/20d is
    two words or one smudged one.
    """
    t = _tok()
    out = ""
    for top, bot, cls in _H:
        c = f' class="{cls}"' if cls else ""
        lead = (f'<span style="display:block;font-size:10px;font-weight:600;'
                f'color:{t.get("body")};letter-spacing:.07em;'
                f'margin-bottom:1px">{top}</span>' if top else "")
        out += (f'<th{c} style="color:{t.get("ink")};font-weight:600">'
                f"{lead}{bot}</th>")
    return out


def margins(d: dict, sort: str = "RV %ile") -> str:
    """Financials above, Commodities below.

    Stacked rather than side by side: this table is fourteen columns wide, and
    two of them across a laptop would wrap every number. The Board can sit
    side by side because it carries six narrow columns; this one cannot.

    Column order is live-first. Everything through RSI moves daily; margin and
    notional are reference, kept so the arithmetic is checkable but no longer
    occupying the position the eye reaches first.
    """
    t = _tok()
    key, desc = MARGIN_SORTS.get(sort, MARGIN_SORTS["RV %ile"])
    flag = f'<div class="flag">{esc(d["warn"])}</div>' if d.get("warn") else ""

    def pcell(p):
        if p is None:
            return '<td class="faint">—</td>'
        cls = "warn" if p >= 80 else "pos" if p <= 20 else "dim"
        return f'<td class="{cls}">{p:.0f}</td>'

    def rsicell(v):
        # Wilder's own thresholds. Coloured opposite to the vol columns on
        # purpose: a high RV percentile is a risk warning, a high RSI is a
        # directional reading, and using the same colour for both would
        # invite reading them as the same kind of statement.
        if v is None:
            return '<td class="faint">—</td>'
        cls = "warn" if v >= 70 else "pos" if v <= 30 else "dim"
        return f'<td class="{cls}">{v:.0f}</td>'

    def zcell(z):
        # ±2σ is the threshold, not ±1. On log-vol over a year a reading
        # beyond one sigma happens roughly a third of the time and colouring
        # it would light most of the table; beyond two is genuinely unusual.
        if z is None:
            return '<td class="faint">—</td>'
        cls = "warn" if z >= 2 else "pos" if z <= -2 else "dim"
        return f'<td class="{cls}">{z:+.1f}</td>'

    def panel(group):
        rows = [r for r in d["rows"] if r.get("group") == group]
        if not rows:
            return ""
        rows.sort(key=lambda r: (r.get(key) is None,
                                 -(r.get(key) or 0) if desc else (r.get(key) or 0)))
        body = ""
        for r in rows:
            vp = r.get("volPct")
            # The wash keys off RV, not ATR. They agree most of the time, and
            # tinting on both would give two rows the same colour for
            # different reasons — which is worse than tinting on one.
            tint = ""
            if vp is not None and vp >= 80:
                tint = f'background:{t.get("amber")}1a'
            elif vp is not None and vp <= 20:
                tint = f'background:{t.get("teal")}14'
            body += (f'<tr style="{tint}"><td class="l">'
                     f'{swatch(r.get("sector", ""))}{esc(r.get("code"))} '
                     f'<span class="nm">{esc(r.get("name"))}</span></td>'
                     # Last in the reading ink: it is the number every other
                     # column is derived from, so it should not be the
                     # faintest thing on the row.
                     f'<td style="color:{t.get("ink")}">'
                     f'{num(r.get("last"), r.get("dec", 2)) or "—"}</td>'
                     + cell(r.get("annVol"), 1) + cell(r.get("vol100"), 1, "dim")
                     + pcell(vp) + zcell(r.get("volZ"))
                     + cell(r.get("atr"), 0) + cell(r.get("atr100"), 0, "dim")
                     + pcell(r.get("atrPct")) + zcell(r.get("atrZ"))
                     + rsicell(r.get("rsi"))
                     + cell(r.get("margVol"), 2) + cell(r.get("daysATR"), 1, "dim")
                     + cell(r.get("marginPct"), 2, "dim")
                     + cell(r.get("maint"), 0, "dim")
                     + cell(r.get("notional"), 0, "dim") + "</tr>")
        return eyebrow(group) + table(_head(), body)

    return flag + panel("Financials") + panel("Commodities")


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
            '<th>Notional</th><th class="l">Small</th><th>Multiplier</th>'
            '<th>Notional</th><th>Fraction</th>')
    body = ""
    for c in U.CODES:
        m, mic, px = U.MULT.get(c), U.MICRO.get(c), last.get(c)
        notl = px * m if (px and m) else None
        body += (f'<tr><td class="l">{swatch(U.SECTOR[c])}{esc(c)} '
                 f'<span class="nm">{esc(U.NAME[c])}</span></td>'
                 + cell(px, U.DEC.get(c, 2), "dim")
                 + cell(m, 0, "dim")
                 + f'<td style="color:{ink};font-weight:600">'
                 + (f'{notl:,.0f}' if notl else "—") + "</td>"
                 + (f'<td class="l" style="color:{ink}">{esc(mic[0])}</td>'
                    + cell(mic[1], 0, "dim")
                    + cell(px * mic[1] if px else None, 0, "dim")
                    + f'<td class="dim">1/{mic[2]}</td>'
                    if mic else
                    '<td class="l faint">—</td><td class="faint">—</td>'
                    '<td class="faint">—</td><td class="faint">—</td>')
                 + "</tr>")
    return (eyebrow("Contract specifications")
            + note("Notional = last × multiplier, priced off the same daily "
                   "closes as the Board. The small contract is what makes a "
                   "computed ratio executable — a 1.6 : 1 spread is 8 : 1 in "
                   "micros. Specifications are transcribed, not fetched: "
                   "<b>check against CME before trading off them</b>.")
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
