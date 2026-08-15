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
         "composite = equal-weight rank on Sharpe, ER and Win%.",
         "ER = Kaufman efficiency: |net move| / path length.", "",
         _pad("#", 3) + " " + _pad("LONG", 6) + _pad("SHORT", 6) +
         _pad("SECTOR", 9) + _rpad("SCORE", 7) + _rpad("SHRP", 7) +
         _rpad("ER", 7) + _rpad("WIN%", 6) + _rpad("TOT%", 8) +
         _rpad("VOL%", 7) + _rpad("MDD%", 7) + _rpad("CORR", 6)]
    for r in p["rows"]:
        L.append(_rpad(r["n"], 3) + " " + _pad(r["long"] or "cash", 6) +
                 _pad(r["short"] or "cash", 6) +
                 _pad(str(r["sector"])[:8], 9) +
                 _rpad(_fx(r["score"], 1), 7) + _rpad(_fx(r["sharpe"], 2), 7) +
                 _rpad(_fx(r["er"], 3), 7) + _rpad(_fx(r["win"], 0), 6) +
                 _rpad(_sfx(r["tot"], 2), 8) + _rpad(_fx(r["vol"], 1), 7) +
                 _rpad(_fx(r["mdd"], 2), 7) + _rpad(_fx(r["corr"], 2), 6))
    L += ["", "leg concentration in the top 20 — one ticker dominating the "
              "short", "column means the field is one macro bet replicated",
          "  short: " + "  ".join(f"{a}x{b}" for a, b in p["legShort"]),
          "  long:  " + "  ".join(f"{a}x{b}" for a, b in p["legLong"])]
    if p.get("dropped"):
        L += ["", "dropped for thin coverage: " + ", ".join(p["dropped"])]
    return "\n".join(L)


def spreads(d: dict, per: str) -> str:
    p = d["data"][per]

    # One window's winner is an artefact until the neighbours agree, and where
    # the best OUTRIGHT landed says whether spreading earned its complexity.
    sum_head = ('<th class="l">Window</th><th class="l">Top candidate</th>'
                '<th class="l">Kind</th><th>Sharpe</th><th>± SE</th><th>ER</th>'
                '<th>Tot%</th><th>Bars</th><th class="l">Best outright</th>'
                "<th>at #</th>")
    sum_body = ""
    for r in d.get("summary", []):
        on = "out" if r["window"] == per else ""
        sum_body += (
            f'<tr class="{on}"><td class="l">{esc(r["window"])}</td>'
            f'<td class="l">{esc(r.get("label") or "—")}</td>'
            f'<td class="l {"sh" if r.get("kind") == "outright" else "lg"}">'
            f'{esc(r.get("kind") or "—")}</td>'
            + cell(r.get("sharpe"), 2, "last") + cell(r.get("se"), 2, "faint")
            + cell(r.get("er"), 3, "dim") + pct(r.get("tot"), 1)
            + cell(r.get("bars"), 0, "faint")
            + f'<td class="l dim">{esc(r.get("bestOut") or "—")}</td>'
            + cell(r.get("outRank"), 0,
                   "sh" if (r.get("outRank") or 99) <= 5 else "faint")
            + "</tr>")

    pers = (d.get("persist") or [])[:8]
    pers_head = ('<th class="l">Position</th><th class="l">Kind</th>'
                 '<th>Windows</th><th>Best #</th><th>Avg #</th>'
                 '<th>Med Sharpe</th><th>Med ER</th><th class="l">Appears in</th>')
    nw = d.get("nWindows", 9)
    pers_body = ""
    for r in pers:
        strong = "out" if r["count"] >= -(-nw // 2) else ""
        pers_body += (
            f'<tr class="{strong}"><td class="l">{esc(r["label"])}</td>'
            f'<td class="l {"sh" if r["kind"] == "outright" else "lg"}">'
            f'{esc(r["kind"])}</td>'
            f'<td class="last">{r["count"]}/{nw}</td>'
            + cell(r["best"], 0, "dim") + cell(r["avgRank"], 1, "dim")
            + cell(r["medSharpe"], 2, "dim") + cell(r["medER"], 3, "dim")
            + f'<td class="l faint">{esc(" ".join(r["windows"]))}</td></tr>')

    verdict = []
    if p.get("bestPair"):
        verdict.append(f'best pair <b>{esc(p["bestPair"])}</b>')
    if p.get("bestOut"):
        verdict.append(f'best outright <b>{esc(p["bestOut"])}</b> at rank '
                       f'{p["outRank"]}')
    verdict.append(f'median Sharpe — pairs <b>{p["medPair"]}</b>, outrights '
                   f'<b>{p["medOut"]}</b>')
    if p["medOut"] >= p["medPair"]:
        verdict.append("<b>outrights win the like-for-like — spreading is not "
                       "paying on this horizon</b>")

    # On a short span the Sharpe column is not evidence, and that fact needs to
    # be ON the screen — but as a flag, not a paragraph.
    warn = ""
    weak = p["se"] > 2.5
    if weak:
        warn = (f'<div class="flag">Sharpe unsupportable at {p["span"]} days — '
                f'noise alone tops out near {round(p["noise"])} over '
                f'{p["nField"]} candidates. Rank on ER.</div>')

    head = ('<th class="l">#</th><th class="l">Long</th><th class="l">Short</th>'
            '<th class="l">Sector</th><th>Score</th>'
            f'<th{" class=\"dim\"" if weak else ""}>Sharpe</th>'
            f'<th{" class=\"on\"" if weak else ""}>ER</th>'
            "<th>Win%</th><th>Tot%</th><th>Vol%</th><th>MDD%</th>"
            "<th>Corr</th><th>Ratio</th>")
    body = ""
    for r in p["rows"]:
        lg = (f'<span class="lg">{esc(r["long"])}</span>' if r["long"]
              else '<span class="cash">cash</span>')
        sh = (f'<span class="sh">{esc(r["short"])}</span>' if r["short"]
              else '<span class="cash">cash</span>')
        er_cls = ("pos" if (r["er"] or 0) >= 0.30
                  else "dim" if (r["er"] or 0) >= 0.12 else "faint")
        sharpe_cls = ("faint" if weak
                      else ("pos" if (r["sharpe"] or 0) >= 0 else "neg"))
        body += (f'<tr class="{"out" if r["kind"] == "outright" else ""}">'
                 f'<td class="l faint">{r["n"]}</td><td class="l">{lg}</td>'
                 f'<td class="l">{sh}</td>'
                 f'<td class="l faint">{esc(r["sector"])}</td>'
                 + cell(r["score"], 1, "dim") + cell(r["sharpe"], 2, sharpe_cls)
                 + cell(r["er"], 3, er_cls) + cell(r["win"], 0, "dim")
                 + pct(r["tot"], 1) + cell(r["vol"], 1, "dim")
                 + cell(r["mdd"], 1, "neg") + cell(r["corr"], 2, "dim")
                 + cell(r["ratio"], 2, "dim") + "</tr>")

    return (eyebrow("Optimal by window")
            + note("Top-ranked candidate in each window on the same weighting. "
                   "A position that holds across neighbouring windows is a "
                   "different object from one that only wins the shortest.")
            + table(sum_head, sum_body)
            + (eyebrow("Holds across windows")
               + note("How often each position appears in the top 10 of a "
                      "window, ranked by count then by average rank — appearing "
                      "8th in six windows is worth more than 1st in one. This is "
                      "the closest thing here to evidence that a relationship is "
                      "structural rather than lucky.")
               + table(pers_head, pers_body) if pers else "")
            + chips([p["note"],
                     f'{p["bars"]} bars · {p["instruments"]} instruments',
                     f'Sharpe SE ±{p["se"]}', f'{p["start"]} → {p["end"]}',
                     "vol-adjusted legs", f'cap {d["cap"]}:1'])
            + note(" · ".join(verdict)) + warn
            + spread_charts(p) + table(head, body))


def spread_charts(p: dict) -> str:
    """Both legs rebased to 100, with the vol-adjusted spread over them. The
    table cannot separate a spread that worked because both legs trended from
    one that worked because a leg collapsed. This can, at a glance."""
    if not p.get("charts"):
        return ""
    cards = ""
    for c in p["charts"]:
        series = []
        if c.get("lg"):
            series.append({"k": c["lgName"], "v": c["lg"], "c": C["pos"],
                           "w": 1.2, "o": 0.85})
        if c.get("sh"):
            series.append({"k": c["shName"], "v": c["sh"], "c": C["neg"],
                           "w": 1.2, "o": 0.85})
        series.append({"k": "spread", "v": c["sp"], "c": C["deep"], "w": 2.2})
        legend = "".join(f'<span class="key"><i class="sw" '
                         f'style="background:{s["c"]}"></i>{esc(s["k"])}</span>'
                         for s in series)
        cards += (f'<div class="plot"><div class="ctitle"><b>{c["n"]}. '
                  f'{esc(c["label"])}</b><span>Sharpe {c["sharpe"]} · ER '
                  f'{c["er"]} · {"+" if c["tot"] >= 0 else ""}{c["tot"]}%'
                  f'</span></div><div class="clegend">{legend}</div>'
                  + CH.line_chart(c["t"], series, None, 560, 170, 1) + "</div>")
    return (eyebrow("Why they ranked")
            + note("Both legs rebased to 100 at the window open, with the "
                   "vol-adjusted spread over them.")
            + f'<div class="cgrid">{cards}</div>')


# ------------------------------------------------------------------ Curve
def curve(d: dict, code: str) -> str:
    curves = d.get("curves", {})
    if not curves:
        return ('<div class="skel">No settlement data in the last build — CME '
                "may have refused the runner. It usually returns on the next "
                "run.</div>")
    scan = sorted(curves.values(), key=lambda r: -(r.get("carryAnn") or -99))
    head = ('<th class="l">Symbol</th><th class="l">Sector</th><th>Front</th>'
            '<th>Back</th><th class="l">Shape</th><th>Roll %</th>'
            "<th>Carry ann %</th>")
    body = "".join(
        f'<tr><td class="l">{esc(r["code"])}</td>'
        f'<td class="l faint">{esc(r["sector"])}</td>'
        + cell(r["front"], 2, "dim") + cell(r["back"], 2, "dim")
        + f'<td class="l {"pos" if r["shape"] == "Backwardation" else "neg"}">'
        f'{esc(r["shape"])}</td>' + pct(r["rollPct"], 2)
        + pct(r["carryAnn"], 1) + "</tr>" for r in scan)

    c = curves[code]
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
        f'<tr><td class="l">{esc(r["month"])}</td>' + cell(r["settle"], 2)
        + f'<td class="dim">{esc(r.get("chg") or "—")}</td>'
        f'<td class="dim">{esc(r.get("vol") or "—")}</td>'
        f'<td class="dim">{esc(r.get("oi") or "—")}</td></tr>'
        for r in c["rows"])

    return (note("Term structure from CME settlements"
                 + (f' · trade date {esc(d.get("tradeDate"))}'
                    if d.get("tradeDate") else "")
                 + ". Positive carry is backwardation — a roll tailwind for "
                   "longs; negative is contango, a roll drag.")
            + eyebrow("Carry scanner — most backwardated first")
            + table(head, body)
            + note(f'<b>{esc(c["code"])}</b> · {esc(c["frontMonth"])} '
                   f'<b>{num(c["front"], 2)}</b> → {esc(c["backMonth"])} '
                   f'<b>{num(c["back"], 2)}</b> · {esc(c["shape"])} {arrow} · '
                   f'current roll {"+" if c["rollPct"] >= 0 else ""}'
                   f'{num(c["rollPct"], 2)}% · carry ann '
                   f'{"+" if c["carryAnn"] >= 0 else ""}{num(c["carryAnn"], 1)}%')
            + '<div class="plot">'
            + CH.line_chart(months,
                            [{"k": "Settle", "v": settle, "c": C["teal"],
                              "w": 2.4}], oi, 1100, 280, 2) + "</div>"
            + eyebrow("Settlements")
            + table('<th class="l">Month</th><th>Settle</th><th>Change</th>'
                    "<th>Volume</th><th>OI</th>", detail))


# ---------------------------------------------------------------- Margins
def margins(d: dict, sort: str = "margVol") -> str:
    rows = sorted(d["rows"],
                  key=lambda r: (r.get(sort) is None, r.get(sort) or 0))
    head = ('<th class="l">Instrument</th><th class="l">Sector</th>'
            "<th>Maint $</th><th>Notional $</th><th>Margin %</th>"
            "<th>Ann vol %</th><th>Marg/Vol</th><th>Days ATR</th>")
    body = "".join(
        f'<tr><td class="l">{esc(r["code"])} {esc(r["name"])}</td>'
        f'<td class="l faint">{esc(r["sector"])}</td>'
        + cell(r["maint"], 0) + cell(r["notional"], 0, "dim")
        + cell(r["marginPct"], 2) + cell(r["annVol"], 1, "dim")
        + cell(r["margVol"], 2) + cell(r["daysATR"], 1, "dim") + "</tr>"
        for r in rows)
    return (note("Overnight <b>maintenance</b> per contract from AMP (retail, "
                 "roughly 10% above raw CME; BTC and ETH come from CME's own "
                 "file). <b>Marg/Vol</b> is margin % ÷ 20-day annualised vol; "
                 "<b>Days ATR</b> is margin ÷ daily dollar range. Lowest "
                 "Marg/Vol first — thinnest cushion against risk, and the "
                 "first candidates for a margin hike.")
            + table(head, body))


# ----------------------------------------------------------------- Events
def _next_weekday(wd: int) -> dt.date:
    t = dt.date.today()
    return t + dt.timedelta(days=(wd - t.weekday() + 7) % 7)


def _first_friday(y: int, m: int) -> dt.date:
    d = dt.date(y, m, 1)
    return d + dt.timedelta(days=(4 - d.weekday() + 7) % 7)


def _next_first_friday() -> dt.date:
    t = dt.date.today()
    f = _first_friday(t.year, t.month)
    if f < t:
        f = _first_friday(t.year + (t.month == 12), t.month % 12 + 1)
    return f


def _last_business_day() -> dt.date:
    t = dt.date.today()

    def eom(y, m):
        d = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        while d.weekday() > 4:
            d -= dt.timedelta(days=1)
        return d

    d = eom(t.year, t.month)
    return d if d >= t else eom(t.year + (t.month == 12), t.month % 12 + 1)


def _next_month_day(day: int) -> dt.date:
    t = dt.date.today()
    d = t.replace(day=day)
    if d < t:
        d = (t.replace(day=1) + dt.timedelta(days=32)).replace(day=day)
    return d


def _next_from(lst) -> dt.date:
    t = dt.date.today()
    up = [dt.date.fromisoformat(s) for s in lst
          if dt.date.fromisoformat(s) >= t]
    return up[0] if up else None


FOMC = ["2026-09-16", "2026-10-28", "2026-12-09", "2027-01-27"]
CPI = ["2026-08-12", "2026-09-11", "2026-10-13", "2026-11-12", "2026-12-10"]

EVENTS = [
    ("EIA Petroleum Status", lambda: _next_weekday(2), "10:30", "High", ["CL"], True),
    ("EIA Nat Gas Storage", lambda: _next_weekday(3), "10:30", "High", ["NG"], True),
    ("API Crude (private)", lambda: _next_weekday(1), "16:30", "Med", ["CL"], True),
    ("Nonfarm Payrolls", _next_first_friday, "08:30", "High",
     ["ES", "NQ", "NKD", "GC", "SI", "6E", "6J"], True),
    ("Jobless Claims", lambda: _next_weekday(3), "08:30", "Med", ["ES", "NQ"], True),
    ("FOMC Rate Decision", lambda: _next_from(FOMC), "14:00", "High",
     ["ES", "NQ", "GC", "SI", "HG", "6E", "6J"], True),
    ("CPI Inflation", lambda: _next_from(CPI), "08:30", "High",
     ["ES", "NQ", "GC", "SI", "6E", "6J"], True),
    ("PCE Inflation", _last_business_day, "08:30", "High",
     ["ES", "NQ", "GC", "SI"], False),
    ("USDA WASDE", lambda: _next_month_day(12), "12:00", "High",
     ["ZC", "ZS", "ZW"], False),
    ("USDA Crop Progress", lambda: _next_weekday(0), "16:00", "Med",
     ["ZC", "ZS"], False),
    ("USDA Export Sales", lambda: _next_weekday(3), "08:30", "Med",
     ["ZC", "ZS", "ZW"], True),
]


def event_codes():
    return ["All"] + [c for c in U.CODES
                      if any(c in e[4] for e in EVENTS)]


def events(filt: str = "All") -> str:
    t = dt.date.today()
    rows = []
    for name, fn, time, impact, affects, exact in EVENTS:
        try:
            d = fn()
        except Exception:
            d = None
        if not d or (filt != "All" and filt not in affects):
            continue
        days = (d - t).days
        when = ("today" if days == 0 else "tomorrow" if days == 1
                else f"in {days}d")
        rows.append((d, when, name, time, impact, " ".join(affects), exact))
    rows.sort(key=lambda r: r[0])

    head = ('<th class="l">Date</th><th class="l">Time ET</th>'
            '<th class="l">Event</th><th class="l">Impact</th>'
            '<th class="l">Affects</th><th class="l">Countdown</th>')
    body = "".join(
        f'<tr><td class="l">{"" if r[6] else "≈ "}'
        f'{esc(r[0].strftime("%a %b %d"))}</td>'
        f'<td class="l dim">{r[3]}</td><td class="l">{esc(r[2])}</td>'
        f'<td class="l {"neg" if r[4] == "High" else "dim"}">{r[4]}</td>'
        f'<td class="l faint">{esc(r[5])}</td>'
        f'<td class="l dim">{r[1]}</td></tr>' for r in rows)

    return (note("Next scheduled catalyst per contract, computed from calendar "
                 "rules — so these stay correct even if the price data is a day "
                 "stale. <b>≈</b> marks an estimate; verify before trading. "
                 "Euro and Yen also move on ECB and BOJ decisions, which are "
                 "not on this list.")
            + (table(head, body) if rows else
               '<div class="skel">No upcoming events for that selection.</div>'))


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
def _tok() -> dict:
    """Live tokens for the few places that need an inline style."""
    from sk_ui import tokens
    import streamlit as st
    return tokens(st.session_state.get("dark", True))


def news(markets: dict) -> str:
    """Fetched server-side now rather than through a CORS proxy in the browser.
    That removes the one tab that depended on a third party neither we nor the
    exchange controls."""
    if not markets:
        return ('<div class="skel">No commentary came back — Trading Economics '
                "may be refusing this host. Try Refresh.</div>")
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
            items += (
                f'<div class="mkt"><h6>{esc(code)}  {esc(U.NAME[code])}</h6>'
                f'<p style="text-align:left;hyphens:none">{esc(m["blurb"])}</p>'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:baseline;margin-top:10px;padding-top:8px;'
                f'border-top:1px solid {t["line"]}">'
                f'<span style="font-size:11px;color:{t["faint"]}">'
                f'{esc(m.get("date") or "")}</span>{link}</div></div>')
        if items:
            cols += (f'<div>{eyebrow(group)}<div class="card">{items}</div>'
                     f"</div>")
    return f'<div class="grid2 news">{cols}</div>'
