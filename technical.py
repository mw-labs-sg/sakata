"""Technical tab — Range Levels engine (matrix · breakdown · drill-down)."""
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_hex

from common import _session, SYMBOLS


TA_INK, TA_TEAL = "#0f172a", "#0f766e"
TA_GREEN, TA_RED, TA_AMBER = "#15803d", "#b91c1c", "#c8922e"
TA_GREY, TA_LIVE = "#94a3b8", "#fef9ec"
TA_FONT = "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
TA_HEAT = LinearSegmentedColormap.from_list(
    "ta_heat", ["#c15a52", "#dfa79c", "#f0d7cf", "#f5f3ee", "#cbdcc7", "#93bb9d", "#4f9673"])
TA_DASH = "\u2013"
TA_LEN1, TA_LEN2 = 100, 200
TA_CHART_BARS = 180

TA_LADDER = {
    "Intra-Day":     dict(bar="1h",  seg="D", period="730d", note="1H bars"),
    "Intra-Week":    dict(bar="1h",  seg="W", period="730d", note="1H bars"),
    "Intra-Month":   dict(bar="4h",  seg="M", period="730d", note="4H bars"),
    "Intra-Quarter": dict(bar="1d",  seg="Q", period="10y",  note="1D bars"),
    "Intra-Year":    dict(bar="1wk", seg="Y", period="max",  note="1W bars"),
}
TA_ORDER = ["Intra-Day", "Intra-Week", "Intra-Month", "Intra-Quarter", "Intra-Year"]  # Day -> Year
TA_SHORT = {"Intra-Day": "Day", "Intra-Week": "Week", "Intra-Month": "Month",
            "Intra-Quarter": "Qtr", "Intra-Year": "Year"}
TA_DEFAULT = ["ES  S&P 500", "NQ  Nasdaq", "ZB  T-Bond", "6E  Euro",
              "BTC  Bitcoin", "CL  Crude", "GC  Gold", "ZC  Corn"]


# --------------------------------------------------------------- data + core
@st.cache_data(ttl=600, show_spinner=False)
def ta_fetch(sym: str, bar: str, period: str):
    native = "1h" if bar == "4h" else bar
    try:
        df = yf.Ticker(sym, session=_session).history(
            period=period, interval=native, auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df.columns = [str(c).lower() for c in df.columns]
    if not {"open", "high", "low", "close"}.issubset(df.columns):
        return None
    df = df[["open", "high", "low", "close"]].dropna()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    if bar == "4h":
        df = (df.resample("4h", label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna())
    return df


def ta_levels(df, seg):
    o = df.copy()
    o["seg"] = o.index.to_period(seg)
    g = o.groupby("seg", sort=True)
    o["cur_high"]  = g["high"].cummax()
    o["cur_low"]   = g["low"].cummin()
    o["prev_high"] = o["seg"].map(g["high"].max().shift(1))
    o["prev_low"]  = o["seg"].map(g["low"].min().shift(1))
    o["mid"] = (o.prev_high + o.prev_low) / 2
    o["rb"]  = (o.cur_high + o.prev_low) / 2
    o["rs"]  = (o.cur_low + o.prev_high) / 2
    o["ma1"] = o.close.rolling(TA_LEN1).mean()
    o["ma2"] = o.close.rolling(TA_LEN2).mean()
    o["pos"] = (o.close - o.prev_low) / (o.prev_high - o.prev_low) * 100
    return o.dropna(subset=["prev_high"])


def ta_read(r):
    if   r.pos > 100: regime, s_rng = "Breakout",   1
    elif r.pos <   0: regime, s_rng = "Breakdown", -1
    else:             regime, s_rng = "Range",      0
    hi, lo = max(r.rb, r.rs), min(r.rb, r.rs)
    if   r.close > hi: retrace, s_ret = "Bull",    1
    elif r.close < lo: retrace, s_ret = "Bear",   -1
    else:              retrace, s_ret = "Neutral", 0
    v100 = "above" if r.close > r.ma1 else "below"
    v200 = "above" if r.close > r.ma2 else "below"
    if   v100 == v200 == "above": trend, s_ma = "Bull",    1
    elif v100 == v200 == "below": trend, s_ma = "Bear",   -1
    else:                         trend, s_ma = "Neutral", 0
    score = s_rng + s_ret + s_ma
    bias = ("Strong Long" if score == 3 else "Long" if score == 2 else "Long tilt" if score == 1
            else "Short tilt" if score == -1 else "Short" if score == -2
            else "Strong Short" if score == -3 else "Neutral")
    return dict(regime=regime, retrace=retrace, trend=trend, v100=v100, v200=v200,
                score=score, bias=bias)


def ta_rr(r):
    nan = dict(rb_stop=np.nan, rs_tgt=np.nan, rr_retrace=np.nan, rr_range=np.nan)
    if not (0 <= r.pos <= 100):
        return nan
    px = r.close
    lo, hi = min(r.rb, r.rs), max(r.rb, r.rs)
    rr_r = (hi - px) / (px - lo) if (px > lo and hi > px) else np.nan
    rr_g = ((r.prev_high - px) / (px - r.prev_low)
            if (px > r.prev_low and r.prev_high > px) else np.nan)
    return dict(rb_stop=lo, rs_tgt=hi, rr_retrace=rr_r, rr_range=rr_g)


def _ta_lab(p):
    return p.start_time.strftime("%d %b %y") if p.freqstr.startswith("W") else str(p)


def _ta_sign(v):
    return (v > 0) - (v < 0)


def _ta_last(sym, tf):
    """Return (levels_frame o, last row r) for one instrument+horizon, or (None, None)."""
    cfg = TA_LADDER[tf]
    df = ta_fetch(sym, cfg["bar"], cfg["period"])
    if df is None or len(df) < TA_LEN2 + 5:
        return None, None
    o = ta_levels(df, cfg["seg"])
    if o.empty:
        return None, None
    return o, o.iloc[-1]


# --------------------------------------------------------------- scanner rows
def _ta_row(name, note, dec, o, r):
    chg = (o.close.iloc[-1] / o.close.iloc[-2] - 1) * 100 if len(o) >= 2 else np.nan
    return dict(rung=name, note=note, dec=dec, close=r.close, chg=chg,
                high=r.prev_high, low=r.prev_low,
                rngpct=(r.prev_high - r.prev_low) / r.prev_low * 100,
                pos=r.pos, mid=r.mid, rb=r.rb, rs=r.rs, ma100=r.ma1, ma200=r.ma2,
                **ta_read(r), **ta_rr(r))


def ta_scan_rows(basket, tf):
    rows = []
    for lbl in basket:
        sym, dec = SYMBOLS[lbl][0], SYMBOLS[lbl][1]
        o, r = _ta_last(sym, tf)
        if r is None:
            continue
        rows.append(_ta_row(lbl, TA_LADDER[tf]["note"], dec, o, r))
    rows.sort(key=lambda x: (x["score"], x["pos"]), reverse=True)
    for i, x in enumerate(rows, 1):
        x["rung"] = f"{i}. {x['rung']}"
    return rows


# --------------------------------------------------------------- scanner HTML
def ta_scanner_html(rows, title, first_col="Asset"):
    posn, scorn = Normalize(-20, 120), Normalize(-3, 3)
    chgn = Normalize(-3, 3)
    mc  = lambda v: TA_GREEN if v == "above" else TA_RED
    sig = lambda v: TA_GREEN if v == "Bull" else TA_RED if v == "Bear" else "#697683"
    rc  = {"Breakout": TA_GREEN, "Breakdown": TA_RED, "Range": "#697683"}
    bc  = lambda b: TA_GREEN if "Long" in b else TA_RED if "Short" in b else "#697683"
    def rrc(v):
        if not np.isfinite(v): return TA_GREY
        return TA_GREEN if v >= 2 else TA_AMBER if v >= 1 else TA_RED
    fnum = lambda v, d: f"{v:,.{d}f}"
    nz   = lambda v, f: TA_DASH if not np.isfinite(v) else f(v)
    chg_hex = lambda v: to_hex(TA_HEAT(chgn(v))) if np.isfinite(v) else "#f5f3ee"
    chgc = lambda v: (TA_GREEN if (np.isfinite(v) and v > 0)
                      else TA_RED if (np.isfinite(v) and v < 0) else TA_GREY)
    def chg_txt(v):
        if not np.isfinite(v): return TA_DASH
        a = "\u25b2" if v > 0 else "\u25bc" if v < 0 else ""
        return f"{a} {v:+.2f}%"

    h = [f'<div style="font-family:{TA_FONT};font-variant-numeric:tabular-nums;'
         f'border-left:3px solid {TA_TEAL};padding-left:10px;margin-bottom:8px;">',
         f'<div style="font-size:12px;font-weight:700;color:{TA_INK};margin-bottom:9px;">{title}</div>',
         '<table style="border-collapse:separate;border-spacing:0;box-shadow:0 1px 4px '
         'rgba(20,40,80,.08);border-radius:8px;overflow:hidden;"><thead><tr>']
    heads = [(first_col, "left"), ("Last", "right"), ("Chg %", "right"),
             ("Rng Hi", "right"), ("Rng Lo", "right"), ("In Rng %", "right"),
             ("RB", "right"), ("RS", "right"),
             ("Regime", "left"), ("Retrace", "left"), ("Trend", "left"), ("Score", "right"),
             ("Bias", "left"), ("R:R Ret", "right"), ("R:R Rng", "right")]
    for c, a in heads:
        h.append(f'<th style="background:{TA_INK};color:#9fb4cd;text-align:{a};font-size:8px;'
                 f'font-weight:600;letter-spacing:.03em;text-transform:uppercase;'
                 f'padding:4px 6px;white-space:nowrap;">{c}</th>')
    h.append('</tr></thead><tbody>')

    for r in rows:
        d = r["dec"]
        def td(v, a="right", col="#20242b", w="600", extra=""):
            return (f'<td style="padding:4px 6px;text-align:{a};font-size:9.5px;color:{col};'
                    f'font-weight:{w};white-space:nowrap;border-bottom:1px solid #eef1f5;{extra}">{v}</td>')
        h.append("<tr>"
            + td(f'{r["rung"]}<span style="color:{TA_GREY};font-weight:500;"> \u00b7 {r["note"]}</span>',
                 "left", "#20242b", "700", "border-right:1px solid #e7ebf0;")
            + td(fnum(r["close"], d), "right", "#141922", "800",
                 f'font-size:10.5px;background:{chg_hex(r.get("chg", np.nan))};')
            + td(chg_txt(r.get("chg", np.nan)), "right", chgc(r.get("chg", np.nan)), "700",
                 "border-right:2px solid #e3e8ef;")
            + td(fnum(r["high"], d), col=TA_GREEN)
            + td(fnum(r["low"], d),  col=TA_RED)
            + td(f'{r["pos"]:,.0f}', "right", "#20242b", "700",
                 f'background:{to_hex(TA_HEAT(posn(r["pos"])))};border-right:1px solid #e7ebf0;')
            + td(fnum(r["rb"], d),  col="#17608f")
            + td(fnum(r["rs"], d),  col="#8a6008", extra="border-right:1px solid #e7ebf0;")
            + td(r["regime"],  "left", rc[r["regime"]], "700")
            + td(r["retrace"], "left", sig(r["retrace"]), "700")
            + td(r["trend"],   "left", sig(r["trend"]), "700")
            + td(f'{r["score"]:+d}', "right", "#20242b", "700",
                 f'background:{to_hex(TA_HEAT(scorn(r["score"])))};')
            + td(r["bias"], "left", bc(r["bias"]), "700", "border-right:1px solid #e7ebf0;")
            + td(nz(r["rr_retrace"], lambda v: f"{v:,.2f}"), "right", rrc(r["rr_retrace"]), "700")
            + td(nz(r["rr_range"],   lambda v: f"{v:,.2f}"), "right", rrc(r["rr_range"]), "700")
            + "</tr>")
    h.append('</tbody></table></div>')
    return "".join(h)


# --------------------------------------------------------------- matrix
def ta_grid_for(label):
    sym = SYMBOLS[label][0]
    cells = {}
    for tf in TA_ORDER:
        o, r = _ta_last(sym, tf)
        if r is None:
            cells[tf] = None; continue
        info = ta_read(r)
        cells[tf] = dict(score=int(info["score"]), bias=info["bias"],
                         regime=info["regime"], pos=float(r.pos))
    return cells


def ta_matrix_html(grid):
    scorn, rown, coln = Normalize(-3, 3), Normalize(-9, 9), Normalize(-14, 14)
    tfs = TA_ORDER
    col_tot = {tf: 0 for tf in tfs}
    rows = []
    for label, cells in grid.items():
        scores = [cells[tf]["score"] for tf in tfs if cells.get(tf)]
        if not scores:
            continue
        rtot = sum(scores)
        signs = [_ta_sign(s) for s in scores if s != 0]
        if   not signs:                 tag, tagc = "Flat",          TA_GREY
        elif all(v > 0 for v in signs): tag, tagc = "Aligned Long",  TA_GREEN
        elif all(v < 0 for v in signs): tag, tagc = "Aligned Short", TA_RED
        else:                           tag, tagc = "Mixed",         TA_AMBER
        for tf in tfs:
            c = cells.get(tf)
            if c: col_tot[tf] += c["score"]
        rows.append(dict(name=label, cells=cells, rtot=rtot, tag=tag, tagc=tagc))
    rows.sort(key=lambda x: x["rtot"], reverse=True)
    grand = sum(col_tot.values())

    def th(txt, a="center"):
        return (f'<th style="background:{TA_INK};color:#cbd5e1;text-align:{a};font-size:9.5px;'
                f'font-weight:700;letter-spacing:.09em;text-transform:uppercase;'
                f'padding:9px 13px;white-space:nowrap;border-bottom:2px solid {TA_TEAL};">{txt}</th>')

    h = [f'<div style="font-family:{TA_FONT};font-variant-numeric:tabular-nums;'
         f'border-left:3px solid {TA_TEAL};padding-left:10px;margin-bottom:6px;">',
         '<table style="border-collapse:separate;border-spacing:0;box-shadow:0 1px 4px '
         'rgba(20,40,80,.08);border-radius:8px;overflow:hidden;"><thead><tr>',
         th("Instrument", "left")]
    for tf in tfs:
        h.append(th(TA_SHORT[tf]))
    h.append(th("Conv") + th("Read", "left"))
    h.append('</tr></thead><tbody>')

    for row in rows:
        cells = row["cells"]
        h.append("<tr>")
        h.append(f'<td style="padding:8px 13px;text-align:left;font-size:10.5px;font-weight:700;'
                 f'color:#1e293b;white-space:nowrap;border-bottom:1px solid #eef1f5;'
                 f'border-right:1px solid #e7ebf0;">{row["name"]}</td>')
        for tf in tfs:
            c = cells.get(tf)
            if not c:
                h.append(f'<td style="padding:8px 10px;text-align:center;color:{TA_GREY};'
                         f'font-size:10px;border-bottom:1px solid #eef1f5;">{TA_DASH}</td>')
                continue
            bg  = to_hex(TA_HEAT(scorn(c["score"])))
            tip = f'{c["bias"]} \u00b7 {c["regime"]} \u00b7 {c["pos"]:.0f}% in range'
            h.append(f'<td title="{tip}" style="padding:8px 10px;text-align:center;font-size:11px;'
                     f'font-weight:800;color:#141922;background:{bg};'
                     f'border-bottom:1px solid #eef1f5;cursor:default;">{c["score"]:+d}</td>')
        h.append(f'<td style="padding:8px 10px;text-align:center;font-size:11px;font-weight:800;'
                 f'color:#141922;background:{to_hex(TA_HEAT(rown(row["rtot"])))};'
                 f'border-left:1px solid #e7ebf0;border-bottom:1px solid #eef1f5;">{row["rtot"]:+d}</td>')
        h.append(f'<td style="padding:8px 13px;text-align:left;font-size:10.5px;font-weight:700;'
                 f'letter-spacing:.01em;color:{row["tagc"]};white-space:nowrap;'
                 f'border-bottom:1px solid #eef1f5;">{row["tag"]}</td>')
        h.append("</tr>")

    h.append(f'<tr><td style="padding:9px 13px;text-align:left;font-size:9.5px;font-weight:700;'
             f'letter-spacing:.09em;text-transform:uppercase;color:#cbd5e1;background:{TA_INK};'
             f'border-top:2px solid {TA_TEAL};">Breadth</td>')
    for tf in tfs:
        v = col_tot[tf]
        h.append(f'<td style="padding:8px 10px;text-align:center;font-size:10.5px;font-weight:800;'
                 f'color:#141922;background:{to_hex(TA_HEAT(coln(v)))};'
                 f'border-top:2px solid {TA_TEAL};">{v:+d}</td>')
    h.append(f'<td style="padding:8px 10px;text-align:center;font-size:11px;font-weight:800;'
             f'color:white;background:{TA_INK};border-top:2px solid {TA_TEAL};">{grand:+d}</td>')
    h.append(f'<td style="background:{TA_INK};border-top:2px solid {TA_TEAL};">'
             f'</td></tr></tbody></table></div>')
    return "".join(h), rows, col_tot, grand


def ta_matrix_read(rows, col_tot, grand):
    tfs = TA_ORDER
    longs  = [r for r in rows if r["rtot"] > 0]
    shorts = [r for r in rows if r["rtot"] < 0]
    mixed  = [r for r in rows if r["tag"] == "Mixed"]
    top_long  = rows[0]  if rows and rows[0]["rtot"]  > 0 else None
    top_short = rows[-1] if rows and rows[-1]["rtot"] < 0 else None
    most_conf = min(mixed, key=lambda r: abs(r["rtot"])) if mixed else None
    posture = "net long" if grand > 2 else "net short" if grand < -2 else "balanced"
    risk_on  = [TA_SHORT[tf] for tf in tfs if col_tot[tf] > 0]
    risk_off = [TA_SHORT[tf] for tf in tfs if col_tot[tf] < 0]

    def line(lead, body, col=TA_INK):
        return (f'<div style="margin:2px 0;font-size:11px;"><b style="color:{col}">{lead}</b> '
                f'<span style="color:#3a4149">{body}</span></div>')

    p = [f'<div style="font-family:{TA_FONT};border-left:3px solid {TA_AMBER};padding:8px 12px;'
         f'margin-bottom:12px;background:{TA_LIVE};border-radius:6px;">']
    p.append(line("Basket posture \u2014",
        f'net score {grand:+d} across {len(rows)} instruments \u00d7 {len(tfs)} horizons '
        f'({posture}). {len(longs)} long-biased, {len(shorts)} short-biased.'))
    if risk_on:
        p.append(line("Risk-on horizons \u2014", ", ".join(risk_on), TA_GREEN))
    if risk_off:
        p.append(line("Risk-off horizons \u2014", ", ".join(risk_off), TA_RED))
    if top_long:
        p.append(line("Strongest long alignment \u2014",
                      f'{top_long["name"]} at {top_long["rtot"]:+d}.', TA_GREEN))
    if top_short:
        p.append(line("Strongest short alignment \u2014",
                      f'{top_short["name"]} at {top_short["rtot"]:+d}.', TA_RED))
    if most_conf:
        p.append(line("Most conflicted \u2014",
                      f'{most_conf["name"]} (horizons disagree, net {most_conf["rtot"]:+d}) '
                      f'\u2014 transition / mean-revert candidate.', TA_AMBER))
    p.append('</div>')
    return "".join(p)


# --------------------------------------------------------------- drill-down
def ta_seg_table(o, n):
    g = o.groupby("seg", sort=True)
    t = pd.DataFrame({"Bars": g.close.size(), "High": g.high.max(), "Low": g.low.min(),
                      "Close": g.close.last(), "MA100": g.ma1.last(), "MA200": g.ma2.last()})
    t["Range %"] = (t.High - t.Low) / t.Low * 100
    t["Chg %"]   = t.Close.pct_change() * 100
    ph, pl = t.High.shift(), t.Low.shift()
    t["vs prior range"] = np.select([t.Close > ph, t.Close < pl],
                                    ["broke out", "broke down"], default="held inside")
    t["vs 100"] = np.where(t.Close > t.MA100, "above", "below")
    t["vs 200"] = np.where(t.Close > t.MA200, "above", "below")
    t.index = [_ta_lab(p) for p in t.index]; t.index.name = "Segment"
    t = t[["Bars", "High", "Low", "Range %", "Close", "Chg %", "vs prior range",
           "MA100", "vs 100", "MA200", "vs 200"]].tail(n)
    return t.iloc[::-1]


def ta_style_grid(t, caption, dec):
    def _css(dfin):
        s = pd.DataFrame("", index=dfin.index, columns=dfin.columns)
        s["Chg %"] = [f"color:{TA_GREEN};font-weight:600" if v > 0 else f"color:{TA_RED};font-weight:600"
                      for v in dfin["Chg %"].fillna(0)]
        s["High"], s["Low"] = f"color:{TA_GREEN}", f"color:{TA_RED}"
        s["Close"] = "color:#20242b;font-weight:700"
        s["vs prior range"] = [f"color:{TA_GREEN};font-weight:700" if v == "broke out"
                               else f"color:{TA_RED};font-weight:700" if v == "broke down"
                               else f"color:{TA_GREY}" for v in dfin["vs prior range"]]
        for c in ("vs 100", "vs 200"):
            s[c] = [f"color:{TA_GREEN};font-weight:600" if v == "above"
                    else f"color:{TA_RED};font-weight:600" for v in dfin[c]]
        for c in ("MA100", "MA200", "Bars", "Range %"):
            s[c] = f"color:{TA_GREY}"
        s.iloc[0] = s.iloc[0] + f";background:{TA_LIVE}"
        return s
    numf = f"{{:,.{dec}f}}"
    return (t.style.apply(_css, axis=None)
             .format({"High": numf, "Low": numf, "Close": numf, "MA100": numf, "MA200": numf,
                      "Range %": "{:,.1f}", "Chg %": "{:,.1f}", "Bars": "{:,.0f}"}, na_rep=TA_DASH)
             .set_caption(caption)
             .set_table_styles([
                {"selector": "", "props": [("font-family", TA_FONT), ("border-collapse", "separate"),
                    ("border-spacing", "0"), ("font-variant-numeric", "tabular-nums"),
                    ("box-shadow", "0 1px 4px rgba(20,40,80,.08)"), ("border-radius", "8px"),
                    ("overflow", "hidden"), ("margin", "0"), ("white-space", "nowrap"),
                    ("border-left", f"3px solid {TA_TEAL}")]},
                {"selector": "caption", "props": [("caption-side", "top"), ("font-size", "11px"),
                    ("font-weight", "700"), ("color", TA_INK), ("padding", "0 0 8px 1px"),
                    ("text-align", "left")]},
                {"selector": "thead th", "props": [("background", TA_INK), ("color", "#f4f7fb"),
                    ("font-weight", "600"), ("padding", "5px 9px"), ("text-align", "right"),
                    ("font-size", "9.5px"), ("border", "none"), ("white-space", "nowrap")]},
                {"selector": "th.index_name", "props": [("background", TA_INK), ("color", "#f4f7fb")]},
                {"selector": "th.row_heading", "props": [("background", "#f5f7fa"), ("color", "#3a4149"),
                    ("font-weight", "600"), ("padding", "5px 10px"), ("text-align", "left"),
                    ("font-size", "10px"), ("border", "none"), ("border-right", "1px solid #e7ebf0")]},
                {"selector": "th.row_heading.level0.row0",
                    "props": [("background", TA_LIVE), ("color", "#8a6008"), ("font-weight", "700"),
                              ("box-shadow", f"inset 3px 0 0 {TA_AMBER}")]},
                {"selector": "td.row0", "props": [("border-bottom", "1px solid #ead9ae")]},
                {"selector": "td", "props": [("padding", "5px 9px"), ("text-align", "right"),
                    ("font-size", "10px"), ("border", "none"), ("border-bottom", "1px solid #eef1f5")]},
                {"selector": "tbody tr:hover td:not(.row0)", "props": [("background", "#fbfcfe")]},
             ]))


def ta_chart_fig(o, name, dec, rr):
    d = o.tail(TA_CHART_BARS); x = np.arange(len(d)); r = d.iloc[-1]
    fig, ax = plt.subplots(figsize=(9.4, 3.15), dpi=150)
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")
    ax.fill_between(x, d.prev_low, d.prev_high, step="post", color=TA_INK, alpha=0.045, lw=0, zorder=0)
    if np.isfinite(rr["rr_retrace"]):
        ax.axhspan(rr["rb_stop"], r.close, color=TA_RED,   alpha=0.05, lw=0)
        ax.axhspan(r.close, rr["rs_tgt"],  color=TA_GREEN, alpha=0.05, lw=0)
    ax.step(x, d.prev_high, where="post", color=TA_GREEN, lw=1.4, zorder=3)
    ax.step(x, d.prev_low,  where="post", color=TA_RED,   lw=1.4, zorder=3)
    ax.step(x, d.mid, where="post", color="#c2c8d2", lw=1.0, ls=(0, (4, 3)), zorder=2)
    ax.step(x, d.rb,  where="post", color="#2f7fb5", lw=1.0, alpha=.75, zorder=2)
    ax.step(x, d.rs,  where="post", color=TA_AMBER,  lw=1.0, alpha=.75, zorder=2)
    ax.plot(x, d.ma1, color="#cfd5dd", lw=1.0, zorder=2)
    ax.plot(x, d.ma2, color="#aab2bd", lw=1.0, zorder=2)
    ax.plot(x, d.close, color=TA_TEAL, lw=1.7, zorder=6)
    ax.scatter([x[-1]], [r.close], s=24, color=TA_TEAL, zorder=7, edgecolor="white", linewidth=1.1)
    fm = lambda v: f"{v:,.{dec}f}"
    for lvl, col, txt in [(r.prev_high, TA_GREEN, "H"), (r.prev_low, TA_RED, "L"),
                          (r.mid, TA_GREY, "Mid"), (r.rb, "#2f7fb5", "RB"), (r.rs, TA_AMBER, "RS")]:
        ax.annotate(f"{txt} {fm(lvl)}", (x[-1], lvl), xytext=(8, 0), textcoords="offset points",
                    color=col, fontsize=7.2, va="center", fontweight="bold")
    ax.annotate(f"{fm(r.close)}", (x[-1], r.close), xytext=(8, 0), textcoords="offset points",
                color="white", fontsize=7.4, va="center", ha="left", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc=TA_TEAL, ec="none"))
    rrt = TA_DASH if not np.isfinite(rr["rr_retrace"]) else f'{rr["rr_retrace"]:,.2f}'
    ax.set_title(f"{name}   \u00b7   {fm(r.close)}   \u00b7   {r.pos:,.0f}% in range   \u00b7   R:R {rrt}",
                 color=TA_INK, fontsize=10, fontweight="bold", loc="left", pad=8)
    ax.grid(color="#eef1f5", lw=0.7)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color("#e2e6ec")
    ax.set_xticks([]); ax.set_xlim(-1, (len(d) - 1) + len(d) * 0.17)
    ax.tick_params(colors="#8b95a1", labelsize=7)
    fig.tight_layout(pad=0.4)
    return fig


# The free TradingView embed can't show CME/ICE futures data ("only available on
# TradingView"), so each instrument maps to a freely-embeddable proxy: US-listed
# ETF, spot, FX, or a TVC continuous index. Close enough for chart-reading; switch
# to the real contract in the chart's own search box if you have a TV data plan.
TV_SYM = {
    "ES  S&P 500": "AMEX:SPY",   "NQ  Nasdaq": "NASDAQ:QQQ",
    "ZB  T-Bond": "NASDAQ:TLT",  "ZN  10Y Note": "NASDAQ:IEF", "SR3  SOFR": "AMEX:SHV",
    "6E  Euro": "FX:EURUSD",     "6J  Yen": "FX:USDJPY",
    "BTC  Bitcoin": "BINANCE:BTCUSDT", "ETH  Ether": "BINANCE:ETHUSDT",
    "CL  Crude": "TVC:USOIL",    "NG  Nat Gas": "AMEX:UNG",
    "GC  Gold": "TVC:GOLD",      "SI  Silver": "TVC:SILVER", "HG  Copper": "AMEX:CPER",
    "ZC  Corn": "AMEX:CORN",     "ZW  Wheat": "AMEX:WEAT",   "ZS  Soybean": "AMEX:SOYB",
    "SB  Sugar": "AMEX:CANE",    "KC  Coffee": "AMEX:JO",
}
TV_DEFAULT = "AMEX:SPY"


def ta_tv_chart(tv_symbol, interval, cid, height=500):
    return (
        '<div class="tradingview-widget-container">'
        f'<div id="{cid}"></div>'
        '<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>'
        '<script type="text/javascript">new TradingView.widget({'
        f'"width":"100%","height":{height},'
        f'"symbol":"{tv_symbol}","interval":"{interval}",'
        '"timezone":"Asia/Singapore","theme":"light","style":"1","locale":"en",'
        '"hide_side_toolbar":false,"allow_symbol_change":true,"withdateranges":true,'
        f'"container_id":"{cid}"' '});</script></div>'
    )


def ta_render_drill(label):
    sym, dec = SYMBOLS[label][0], SYMBOLS[label][1]
    rows = []
    for tf in TA_ORDER:
        o, r = _ta_last(sym, tf)
        if r is None:
            continue
        rows.append(_ta_row(tf, TA_LADDER[tf]["note"], dec, o, r))
    if rows:
        st.markdown(ta_scanner_html(rows, f"{label} — range scanner", first_col="Horizon"),
                    unsafe_allow_html=True)
    tv = TV_SYM.get(label, TV_DEFAULT)
    st.caption(f"Chart proxy: **{tv}** — switch symbol or timeframe in the chart toolbar. "
               "Range-scanner numbers above are the live Yahoo read for the actual contract.")
    components.html(ta_tv_chart(tv, "D", "tv_main"), height=560)


# --------------------------------------------------------------- tab entry
def render_ta() -> None:
    st.caption(
        "Full read — every instrument, every horizon. Alignment **matrix** on top, then toggle the "
        "grouping: **Timeframe breakdown** (one table per horizon, Day → Year, all instruments each) "
        "or **Instrument focus** (one table per name, all horizons). Both show everything; **chart** "
        "at the base. Built to copy wholesale into an LLM."
    )
    all_labels = list(SYMBOLS)
    c1, c2 = st.columns([5, 1])
    with c1:
        basket = st.multiselect("Basket", all_labels, default=all_labels,
                                label_visibility="collapsed", key="ta_basket")
    with c2:
        if st.button("Refresh", key="rta"):
            ta_fetch.clear(); st.rerun()
    if not basket:
        st.info("Pick at least one instrument to scan."); return

    with st.spinner("Building matrix…"):
        grid = {lbl: ta_grid_for(lbl) for lbl in basket}
    table_html, rows, col_tot, grand = ta_matrix_html(grid)
    if not rows:
        st.warning("No data returned for the current basket."); return

    # basket read (full width)
    st.markdown(ta_matrix_read(rows, col_tot, grand), unsafe_allow_html=True)

    # 1 — MATRIX (overview, full width)
    st.markdown("##### Alignment matrix · Day → Year · hover a cell for detail")
    st.markdown(f"<div style='overflow-x:auto'>{table_html}</div>", unsafe_allow_html=True)

    st.markdown("---")
    # 2 — SCANNER: toggle grouping; either mode renders every table
    mode = st.radio("Group by", ["Timeframe breakdown", "Instrument focus"],
                    index=0, horizontal=True, label_visibility="collapsed", key="ta_mode")
    conviction = [r["name"] for r in rows]  # matrix order, strongest first

    if mode == "Timeframe breakdown":
        st.markdown("##### Timeframe breakdown · one table per horizon, all instruments, strongest first")
        for tf in TA_ORDER:
            with st.spinner(f"Scanning {TA_SHORT[tf]}…"):
                srows = ta_scan_rows(basket, tf)
            if srows:
                tf_title = f"{tf} ({TA_LADDER[tf]['note']})"
                st.markdown("<div style='overflow-x:auto'>"
                            + ta_scanner_html(srows, tf_title, first_col="Instrument")
                            + "</div>", unsafe_allow_html=True)
            else:
                st.warning(f"No data on {TA_SHORT[tf]} for this basket.")
    else:
        st.markdown("##### Instrument focus · one table per name, every horizon (Day → Year)")
        for label in conviction:
            sym, dec = SYMBOLS[label][0], SYMBOLS[label][1]
            with st.spinner(f"Scanning {label}…"):
                arows = []
                for tf in TA_ORDER:
                    o, r = _ta_last(sym, tf)
                    if r is None:
                        continue
                    arows.append(_ta_row(tf, TA_LADDER[tf]["note"], dec, o, r))
            if arows:
                st.markdown("<div style='overflow-x:auto'>"
                            + ta_scanner_html(arows, f"{label} · across every horizon", first_col="Horizon")
                            + "</div>", unsafe_allow_html=True)
            else:
                st.warning(f"No usable data for {label}.")

    st.markdown("---")
    # 3 — CHART (instrument focus)
    st.markdown("##### Chart")
    asset = st.selectbox("Instrument", conviction, index=0, key="ta_asset")
    tv = TV_SYM.get(asset, TV_DEFAULT)
    st.markdown(f"<div style='font-size:12px;font-weight:700;color:{TA_INK};margin:2px 0 4px'>"
                f"{asset} \u00b7 <span style='color:#94a3b8;font-weight:500'>{tv}</span></div>",
                unsafe_allow_html=True)
    components.html(ta_tv_chart(tv, "D", "tv_main", 520), height=522)
