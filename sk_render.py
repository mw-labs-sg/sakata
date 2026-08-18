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
                 f'<td style="color:{C["pos"] if tot >= 0 else C["neg"]};'
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
SORTS = {"ER (Adj)": "erAdj", "Win%": "win", "Tot%": "tot", "Sharpe": "sharpe"}


def _optimal(d: dict, per: str, t: dict) -> str:
    """Best spread in each window, in a FIXED row order.

    Not sorted: the five windows always appear as Intraday, WTD, MTD, QTD, YTD
    whether or not each one built, so the block keeps its shape between reloads
    and the eye can go straight to the row it wants. Sorting this one by ER
    (Adj) made the rows move under you as the data changed.
    """
    head = ('<th class="l">Window</th><th class="l">Best spread</th>'
            '<th>ER</th><th>ER (Adj)</th><th>Tot%</th><th>Bars</th>')
    by_win = {r["window"]: r for r in d.get("summary", [])}
    body = ""
    for w in d.get("displayPeriods", d.get("periods", [])):
        r = by_win.get(w)
        on = (f'background:{t.get("teal", "#0d8f83")}1a' if w == per else "")
        if r is None:
            cellhtml = ('<td class="l faint" colspan="5">not built — no window '
                        "of this length in the data</td>")
        else:
            # A short window ranks like any other; the bar count carries the
            # warning. Refusing to draw it hid WTD for the first two days of
            # every week, which is when it is most worth a look.
            bars = cell(r.get("bars"), 0, "warn" if r.get("thin") else "faint")
            cellhtml = (f'<td class="l">{esc(r.get("label") or "—")}</td>'
                        + cell(r.get("er"), 3, "dim")
                        + cell(r.get("erAdj"), 2, "last")
                        + pct(r.get("tot"), 1) + bars)
        body += f'<tr style="{on}"><td class="l">{esc(w)}</td>{cellhtml}</tr>'
    return (eyebrow("Optimal Spread by Time Window")
            + note("ER (Adj) = ER &#215; &#8730;bars. Raw ER decays as "
                   "1/&#8730;n, so the adjusted figure is the one that "
                   "compares across windows — 1.0 is the noise floor.")
            + table(head, body))


def _outrights(d: dict, per: str, t: dict) -> str:
    """ER for every instrument held alone, every window a column.

    Rows sort on the SELECTED window, so the picker at the top of the tab
    reorders this table too — pick YTD and the year's cleanest trends rise to
    the top. Thin windows keep their column: the field ranking needs 20 bars
    before it means anything, but a single instrument's efficiency ratio is
    still a fact about the window, and leaving the column out just looked like
    a bug.
    """
    wins = [w for w in d.get("displayPeriods", [])
            if w in d.get("data", {}) and d["data"][w].get("outER")]
    if not wins:
        return ""
    mats = {w: d["data"][w]["outER"] for w in wins}
    codes = [c for c in U.CODES if any(c in mats[w] for w in wins)]
    if not codes:
        return ""

    skey = per if per in mats else wins[0]
    codes.sort(key=lambda c: (mats[skey].get(c) is None,
                              -(mats[skey].get(c) or 0)))

    vals = [abs(v) for w in wins for v in mats[w].values() if v is not None]
    ref = max(vals) if vals else 1
    ink = t.get("ink", "#0d1418")
    teal = t.get("teal", "#0d8f83")

    head = ('<th class="l">Instrument</th>'
            + "".join(f'<th{" class=\"on\"" if w == skey else ""}>{esc(w)}'
                      f'</th>' for w in wins))
    body = ""
    for c in codes:
        cells = ""
        for w in wins:
            v = mats[w].get(c)
            if v is None:
                cells += '<td class="faint">—</td>'
                continue
            # Explicit ink and weight: these numbers are the table.
            # No wash. Ninety-five tinted cells competed with the numbers they
            # were meant to rank, and the ordering already says what the
            # gradient was saying.
            cells += (f'<td><span style="color:{ink};font-weight:600">'
                      f'{v:.3f}</span></td>')
        body += (f'<tr><td class="l">{swatch(U.SECTOR[c])}{esc(c)} '
                 f'<span class="nm">{esc(U.NAME[c])}</span></td>{cells}</tr>')
    return (eyebrow(f"Outrights by Time Window — ranked on {esc(skey)}")
            + table(head, body))


def spreads(d: dict, per: str, sort: str = "ER (Adj)") -> str:
    p = d["data"][per]
    t = _tok()

    # Reading order: best spread per window, then how the single instruments
    # did, then the full field for the window you picked, then the pictures.
    out = _optimal(d, per, t) + _outrights(d, per, t)

    teal = t.get("teal", "#0d8f83")
    amber = t.get("amber", "#96701c")
    key = SORTS.get(sort, "erAdj")
    rows = sorted(p["rows"], key=lambda r: -(r.get(key) if r.get(key)
                                             is not None else -9e9))
    # Tot% and MDD% adjacent: they are the same question asked twice, what you
    # made and what you gave back on the way.
    head = ('<th class="l">#</th><th class="l">Long</th><th class="l">Short</th>'
            '<th>ER</th><th>ER (Adj)</th><th>Win%</th><th>Vol%</th>'
            '<th>Tot%</th><th>MDD%</th><th>vs leg</th><th>Top 10</th>')
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
            cls = "pos" if dv >= 0 else "neg"
            legcell = f'<td class="{cls}">{"+" if dv >= 0 else ""}{dv:.0f}%</td>'
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
                 + legcell + alsocell + "</tr>")

    return (out
            + eyebrow(f"Spreads by Time Window — {esc(per)}, ranked on "
                      f"{esc(sort)}")
            + note("vs leg is the spread's ER against the better of its two "
                   "legs held alone; negative means it did not pay for itself. "
                   "Top 10 counts the other windows it also ranks in.")
            + table(head, body)
            + chips([p["note"], f'{p["bars"]} bars · {p["instruments"]} '
                     f'instruments', f'{p["start"]} → {p["end"]}',
                     "vol-adjusted legs", f'cap {d["cap"]}:1'])
            + spread_charts(p, t))


def spread_charts(p: dict, t: dict = None) -> str:
    """Legs rebased to 100 in the side colours, spread over them in the ink."""
    if not p.get("charts"):
        return ""
    t = t or _tok()
    ink = t.get("ink", "#0d1418")
    teal, amber = t.get("teal", "#0d8f83"), t.get("amber", "#96701c")
    neg, pos = t.get("neg", "#c2453b"), t.get("pos", "#0a7c66")
    mute, faint = t.get("mute", "#66727b"), t.get("faint", "#97a2ab")
    cards = ""
    for c in p["charts"]:
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

        dv, best = c.get("legDelta"), c.get("bestLegEr")
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
        def stat(label, val, suffix="", col=None):
            if val is None:
                return ""
            return (f'<span style="white-space:nowrap"><span style="color:'
                    f'{faint};font-size:9.5px;letter-spacing:.07em;'
                    f'text-transform:uppercase">{label}</span> '
                    f'<span style="color:{col or ink};font-weight:600">'
                    f'{val}{suffix}</span></span>')

        stats = "".join([
            stat("Sharpe", c.get("sharpe")),
            stat("Win", c.get("win"), "%"),
            stat("Vol", c.get("vol"), "%"),
            stat("MDD", c.get("mdd"), "%", neg),
            stat("Tot", (f'{"+" if (c.get("tot") or 0) >= 0 else ""}'
                         f'{c.get("tot")}') if c.get("tot") is not None
                 else None, "%", pos if (c.get("tot") or 0) >= 0 else neg),
        ])
        legpart = ("" if best is None else
                   f'<span style="color:{mute}"> · leg {best:.3f}</span>')
        cards += (f'<div class="plot"><div class="ctitle">'
                  f'<b>{c["n"]}. {esc(c["label"])}</b>'
                  # ER (Adj) is the ranking key, so it is the number in ink.
                  f'<span><span style="color:{ink};font-weight:700">ER '
                  f'{c["er"]}</span>{legpart}</span></div>'
                  f'<div class="clegend">{legend}{verdict}</div>'
                  f'<div class="cstats">{stats}</div>'
                  + CH.line_chart(c["t"], series, None, 560, 220, 1) + "</div>")
    return (eyebrow("Why they ranked")
            + note("Legs rebased to 100 — turquoise long, orange short — with "
                   "the spread over them. Two charts per instrument at most.")
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
        wk = r["date"].isocalendar()[1]
        if wk != last_week:
            last_week = wk
            body += section(f'Week of {r["date"].strftime("%d %b")}')
        body += row(r)

    flag = ""
    if warn:
        flag = (f'<div class="flag">Hand-maintained schedule exhausted for '
                f'{", ".join(warn)} — those rows will stop appearing until '
                f'the dates are extended in sk_calendar.py.</div>')

    return flag + table(head, body)


# -------------------------------------------------------------- Knowledge
def knowledge(group: str = "All") -> str:
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
    return (note("What actually moves each contract, ordered by how often it "
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
                    f'style="color:{t["teal"]};text-decoration:none;'
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
                f'border-top:1px solid {t["line"]}">'
                f'<span style="font-size:11px;color:{t["faint"]}">'
                f'{esc(m.get("date") or "")}</span>{link}</div></div>')
        if items:
            cols += (f'<div>{eyebrow(group)}<div class="card">{items}</div>'
                     f"</div>")
    return flag + f'<div class="grid2 news">{cols}</div>'
