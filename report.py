"""report.py — runs in GitHub Actions, writes docs/index.html for GitHub Pages.

Why this exists: Yahoo serves residential IPs but rate-limits cloud ranges, so
the Streamlit app works on a laptop and comes back empty when hosted. A runner
fetch is not blocked, so the Action does the work and commits a finished page.
Static HTML also loads instantly on a phone with no cold start and nothing to
babysit.

Local Streamlit stays the place to explore interactively. This is the read-
anywhere view: one section per calendar period, plus a copyable digest.

    python report.py            # writes docs/index.html
    python report.py --dry      # synthetic prices, no network (for testing)
"""
import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import sakata_stats as ss

OUT = Path("docs")
PERIODS = ["WTD", "MTD", "QTD", "YTD"]
MODE = "vol"           # vol-adjusted legs; equal notional lets the loud leg win
RATIO_CAP = 5.0        # above this the sizing is not executable
TOP_N = 25             # rows per period section


# ----------------------------------------------------------------- data
def fetch_closes(interval, period):
    import yfinance as yf
    frames = {}
    for sym in ss.ALL_SYMBOLS:
        try:
            h = yf.Ticker(sym).history(period=period, interval=interval)
            if h.empty:
                print(f"  {interval} {sym}: empty")
                continue
            c = h["Close"].dropna()
            c.index = c.index.tz_localize(None) if c.index.tz else c.index
            if interval == "1d":
                c.index = c.index.normalize()
            frames[sym] = c.groupby(c.index).last()
        except Exception as e:
            print(f"  {interval} {sym} failed: {e}")
    return frames


def synth_closes(interval, period):
    """Deterministic fake prices so --dry exercises the whole path offline."""
    n, freq = (1400, "h") if interval == "1h" else (500, "B")
    idx = pd.date_range(end=dt.datetime.now(), periods=n, freq=freq)
    rng = np.random.default_rng(7)
    out = {}
    for i, s in enumerate(ss.ALL_SYMBOLS):
        vol = 0.002 + 0.001 * (i % 5)
        drift = (0.00004 * ((i % 7) - 3))
        out[s] = pd.Series(
            100 * np.exp(np.cumsum(rng.normal(drift, vol, n))), index=idx)
    return out


def resample(frames, bar):
    rule = {"1h": None, "4h": "4h", "1d": "1D", "1wk": "W-MON"}[bar]
    if rule is None:
        return frames
    return {k: v.resample(rule).last().dropna() for k, v in frames.items()}


# ----------------------------------------------------------------- compute
def build_period(period, daily, hourly):
    bar = ss.PERIOD_BARS[period]
    src = hourly if bar in ("1h", "4h") else daily
    start = pd.Timestamp(ss.period_start(period))
    frames = {k: v[v.index >= start] for k, v in src.items()}
    frames = {k: v for k, v in frames.items() if len(v) >= 5}
    if len(frames) < 2:
        return None
    frames = resample(frames, bar)
    data, dropped, cov = ss.align_frames(frames, intraday=bar in ("1h", "4h"))
    if data is None:
        return None
    data = 100 * (data / data.iloc[0])

    ann = ss.ann_factor_for(data.index)
    outs = ss.compute_outrights(data, ann, allow_short=True)
    pairs = ss.compute_pairs(data, ann, MODE)
    pairs, n_capped = ss.apply_ratio_cap(pairs, RATIO_CAP, MODE)
    field = outs + pairs
    ss.rank_field(field)
    field.sort(key=lambda c: c["_score"])

    span = max((dt.datetime.now() - ss.period_start(period)).days, 1)
    end = ss.period_end(period)
    total = max((end - ss.period_start(period)).days, 1)
    best_out = min((c for c in field if c["kind"] == "outright"),
                   key=lambda c: c["_score"], default=None)
    best_pair = min((c for c in field if c["kind"] == "pair"),
                    key=lambda c: c["_score"], default=None)
    return {
        "period": period, "bar": bar, "bar_name": ss.BAR_NAMES[bar],
        "bars": len(data), "instruments": len(data.columns),
        "span": span, "total": total, "pct": span / total,
        "ends": end, "ann": ann, "se": ss.sharpe_se(span),
        "se_end": ss.sharpe_se(total),
        "field": field, "n_out": len(outs), "n_pair": len(pairs),
        "n_capped": n_capped, "dropped": dropped, "cov": cov,
        "best_out": best_out, "best_pair": best_pair,
        "med_out": float(np.median([c["Sharpe"] for c in outs])) if outs else 0.0,
        "med_pair": float(np.median([c["Sharpe"] for c in pairs])) if pairs else 0.0,
    }


# ----------------------------------------------------------------- digest
def digest(res):
    L, A = [], None
    A = L.append
    p = res
    A(f"SAKATA · {p['period']} · {p['bar_name']} bars")
    A(f"generated    {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC")
    A(f"window       {p['period']} from {ss.period_start(p['period']):%d %b %Y}, "
      f"{p['pct']:.0%} elapsed (day {p['span']} of {p['total']}), closes {p['ends']:%a %d %b}")
    A(f"sample       {p['bars']} bars, {p['instruments']} instruments, "
      f"annualised x{p['ann']:,.0f}")
    A(f"Sharpe SE    +/-{p['se']:.2f} now, +/-{p['se_end']:.2f} at period close")
    A(f"legs         vol-adjusted, leg-ratio cap {RATIO_CAP:.0f}:1"
      + (f", {p['n_capped']} pairs hidden by it" if p["n_capped"] else ""))
    A(f"field        {p['n_out']} outrights + {p['n_pair']} pairs")
    A(f"medians      pair Sharpe {p['med_pair']:.2f} vs outright {p['med_out']:.2f}"
      f"   <- like-for-like; comparing the two BEST favours pairs, more draws")
    noise = p["se"] * 2.8
    A(f"noise floor  expected best-of-{len(p['field'])} Sharpe from pure noise "
      f"~{noise:.0f}. Treat anything below that as unproven.")
    if p["se"] > 2.5:
        A("             NOTE: at this span Sharpe is not supportable. Read the ER")
        A("             column, which describes what happened rather than")
        A("             estimating a forward parameter.")
    A("")
    A("composite = equal-weight rank on Sharpe, ER and Win%.")
    A("ER = Kaufman efficiency: |net move| / path length. 1.00 straight line,")
    A("     0.00 chop going nowhere, negative a clean downtrend.")
    A("")
    A(f"{'#':>3} {'LONG':<6}{'SHORT':<6}{'SECTOR':<9}{'SCORE':>7}{'SHRP':>7}"
      f"{'ER':>7}{'WIN%':>6}{'TOT%':>8}{'VOL%':>7}{'MDD%':>7}{'CORR':>6}{'RATIO':>7}")
    for i, c in enumerate(p["field"][:TOP_N], 1):
        ln = "cash" if c["long"] is None else ss.name_of(c["long"])
        sn = "cash" if c["short"] is None else ss.name_of(c["short"])
        cr = "     -" if pd.isna(c["Corr"]) else f"{c['Corr']:6.2f}"
        rt = "      -" if pd.isna(c["Ratio"]) else f"{c['Ratio']:7.2f}"
        A(f"{i:>3} {ln:<6}{sn:<6}{str(c['Sector'])[:8]:<9}{c['_score']:7.1f}"
          f"{c['Sharpe']:7.2f}{c['ER']:7.3f}{c['Win%']:6.0f}{c['Tot%']:+8.2f}"
          f"{c['Vol%']:7.1f}{c['MDD%']:7.2f}{cr}{rt}")
    lg, sh = ss.leg_frequency(p["field"], 20)
    A("")
    A("leg concentration in the top 20 — one ticker dominating the short column")
    A("means the field is one macro bet replicated, not N independent candidates")
    A("  short: " + "  ".join(f"{ss.name_of(k)}x{v}" for k, v in sh.most_common(6)))
    A("  long:  " + "  ".join(f"{ss.name_of(k)}x{v}" for k, v in lg.most_common(6)))
    if p["dropped"]:
        A("")
        A("dropped for thin coverage: "
          + ", ".join(f"{ss.name_of(x)} ({p['cov'].get(x, 0):.0%})" for x in p["dropped"]))
    return "\n".join(L)


# ----------------------------------------------------------------- html
CSS = """
:root{--bg:#fff;--fg:#0f172a;--mut:#94a3b8;--t2:#64748b;--bdr:#e2e8f0;
--bg3:#f8fafc;--pos:#16a34a;--neg:#dc2626;--acc:#0f766e;--amber:#f59e0b}
*{box-sizing:border-box}
body{margin:0;padding:14px;font-family:Inter,-apple-system,BlinkMacSystemFont,
system-ui,sans-serif;background:var(--bg);color:var(--fg);
-webkit-text-size-adjust:100%}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:1.25rem;margin:0 0 2px;letter-spacing:-.01em}
.sub{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;
margin-bottom:14px}
.tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--bdr);
margin-bottom:12px;position:sticky;top:0;background:var(--bg);padding-top:4px;z-index:5}
.tab{padding:7px 15px;font-size:12.5px;font-weight:600;color:var(--t2);cursor:pointer;
border:none;background:none;border-bottom:2px solid transparent}
.tab.on{color:var(--acc);border-bottom-color:var(--acc)}
.chips{margin:8px 0 10px}
.chip{display:inline-block;padding:3px 9px;margin:0 5px 5px 0;border:1px solid var(--bdr);
border-radius:5px;background:var(--bg3);font-size:10.5px;font-weight:600;color:#475569;
font-variant-numeric:tabular-nums}
.note{font-size:12px;color:var(--t2);line-height:1.55;margin:8px 0}
.warn{background:#fffbeb;border-left:3px solid var(--amber);padding:9px 12px;
font-size:12px;line-height:1.55;margin:10px 0;border-radius:0 4px 4px 0}
.tblwrap{overflow-x:auto;border:1px solid var(--bdr);border-radius:6px;
-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:11.5px;line-height:1.35;
font-variant-numeric:tabular-nums}
thead th{background:var(--bg3);color:#475569;font-weight:600;font-size:9px;
text-transform:uppercase;letter-spacing:.05em;padding:6px 8px;text-align:right;
border-bottom:1px solid var(--bdr);white-space:nowrap;position:sticky;top:0}
thead th.l{text-align:left}
td{padding:5px 8px;text-align:right;border-bottom:1px solid #eef2f6;white-space:nowrap}
td.l{text-align:left}
tr.out{background:linear-gradient(90deg,var(--bg3),transparent)}
.lg{color:var(--pos);font-weight:600}.sh{color:var(--amber);font-weight:600}
.cash{color:var(--mut);font-style:italic}
.pos{color:var(--pos);font-weight:600}.neg{color:var(--neg);font-weight:600}
.dim{color:var(--t2)}.faint{color:var(--mut)}
details{margin:14px 0;border:1px solid var(--bdr);border-radius:6px;overflow:hidden}
summary{padding:9px 12px;background:var(--bg3);cursor:pointer;font-size:12px;
font-weight:600;color:#475569}
pre{margin:0;padding:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
font-size:10.5px;line-height:1.45;overflow-x:auto;background:#fcfdfe;
-webkit-overflow-scrolling:touch;white-space:pre}
.cp{margin:8px 12px;padding:5px 13px;font-size:11px;font-weight:600;
text-transform:uppercase;letter-spacing:.05em;border:1px solid var(--bdr);
border-radius:5px;background:#fff;color:#475569;cursor:pointer}
.cp:active{border-color:var(--acc);color:var(--acc)}
.sec{display:none}.sec.on{display:block}
@media(max-width:640px){body{padding:9px}h1{font-size:1.1rem}
table{font-size:10.5px}td,thead th{padding:4px 6px}}
"""

JS = """
function show(p){
 document.querySelectorAll('.sec').forEach(function(s){s.classList.toggle('on',s.id==='s-'+p)});
 document.querySelectorAll('.tab').forEach(function(t){t.classList.toggle('on',t.dataset.p===p)});
 location.hash=p;
}
function cp(id,btn){
 var t=document.getElementById(id).innerText;
 var done=function(){btn.textContent='Copied';setTimeout(function(){btn.textContent='Copy digest'},1600)};
 if(navigator.clipboard&&navigator.clipboard.writeText){
   navigator.clipboard.writeText(t).then(done,function(){fb()})
 }else{fb()}
 function fb(){
   var a=document.createElement('textarea');a.value=t;a.style.position='fixed';
   a.style.opacity=0;document.body.appendChild(a);a.select();
   try{document.execCommand('copy');done()}catch(e){}
   document.body.removeChild(a);
 }
}
window.addEventListener('DOMContentLoaded',function(){
 var h=(location.hash||'').replace('#','');
 show(document.getElementById('s-'+h)?h:'MTD');
});
"""


def cell(v, fmt="{:.2f}", cls=""):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '<td class="faint">—</td>'
    return f'<td class="{cls}">{fmt.format(v)}</td>'


def table_html(res):
    cols = [("#", "l"), ("LONG", "l"), ("SHORT", "l"), ("SECTOR", "l"),
            ("SCORE", ""), ("SHARPE", ""), ("ER", ""), ("WIN%", ""),
            ("TOT%", ""), ("VOL%", ""), ("MDD%", ""), ("CORR", ""), ("RATIO", "")]
    h = "".join(f'<th class="{c}">{n}</th>' for n, c in cols)
    rows = []
    for i, c in enumerate(res["field"][:TOP_N], 1):
        is_out = c["kind"] == "outright"
        ln = ('<span class="cash">cash</span>' if c["long"] is None
              else f'<span class="lg">{html.escape(ss.name_of(c["long"]))}</span>')
        sn = ('<span class="cash">cash</span>' if c["short"] is None
              else f'<span class="sh">{html.escape(ss.name_of(c["short"]))}</span>')
        er_cls = "pos" if c["ER"] >= 0.30 else ("dim" if c["ER"] >= 0.12 else "faint")
        rows.append(
            f'<tr class="{"out" if is_out else ""}">'
            f'<td class="l faint">{i}</td><td class="l">{ln}</td><td class="l">{sn}</td>'
            f'<td class="l faint" style="font-size:10px">{html.escape(str(c["Sector"]))}</td>'
            + cell(c["_score"], "{:.1f}", "dim")
            + cell(c["Sharpe"], "{:.2f}", "pos" if c["Sharpe"] >= 0 else "neg")
            + cell(c["ER"], "{:.3f}", er_cls)
            + cell(c["Win%"], "{:.0f}%", "dim")
            + cell(c["Tot%"], "{:+.1f}%", "pos" if c["Tot%"] >= 0 else "neg")
            + cell(c["Vol%"], "{:.1f}%", "dim")
            + cell(c["MDD%"], "{:.1f}%", "neg")
            + cell(c["Corr"], "{:.2f}", "dim")
            + cell(c["Ratio"], "{:.2f}", "dim")
            + "</tr>")
    return (f'<div class="tblwrap"><table><thead><tr>{h}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def section_html(res):
    p = res
    chips = [f"{p['period']} · {p['bar_name']} bars",
             f"{p['bars']} bars · {p['instruments']} instruments",
             f"Sharpe SE ±{p['se']:.1f} → ±{p['se_end']:.1f} at close",
             f"{p['pct']:.0%} elapsed · closes {p['ends']:%d %b}",
             "vol-adjusted legs", f"cap {RATIO_CAP:.0f}:1"]
    chip_html = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in chips)

    bo, bp = p["best_out"], p["best_pair"]
    verdict = []
    if bo:
        verdict.append(f"best outright <b>{html.escape(ss.pos_label(bo))}</b>")
    if bp:
        verdict.append(f"best pair <b>{html.escape(ss.pos_label(bp))}</b>")
    verdict.append(f"median Sharpe — pairs <b>{p['med_pair']:.2f}</b>, "
                   f"outrights <b>{p['med_out']:.2f}</b>")
    if p["med_out"] >= p["med_pair"]:
        verdict.append("<b>outrights win the like-for-like — spreading is not "
                       "paying on this horizon</b>")

    warn = ""
    if p["se"] > 2.5:
        warn = (f'<div class="warn"><b>At {p["span"]} calendar days the Sharpe '
                f'standard error is ±{p["se"]:.1f}</b>, so the composite is not '
                f'supportable here — a Sharpe of 6 is barely two SE from zero. '
                f'Read the ER column instead: it describes what the window did '
                f'rather than estimating a forward parameter. Bar size cannot '
                f'help, because SE depends only on calendar span. Expected '
                f'best-of-{len(p["field"])} Sharpe from pure noise is '
                f'~{p["se"] * 2.8:.0f}.</div>')

    dg = html.escape(digest(res))
    return (f'<div class="sec" id="s-{p["period"]}">'
            f'<div class="chips">{chip_html}</div>'
            f'<div class="note">{" · ".join(verdict)}</div>'
            f'{warn}{table_html(res)}'
            f'<details open><summary>Digest — copy this to analyse</summary>'
            f'<button class="cp" onclick="cp(\'d-{p["period"]}\',this)">Copy digest</button>'
            f'<pre id="d-{p["period"]}">{dg}</pre></details></div>')


def build_html(results):
    tabs = "".join(
        f'<button class="tab" data-p="{r["period"]}" '
        f'onclick="show(\'{r["period"]}\')">{r["period"]}</button>' for r in results)
    secs = "".join(section_html(r) for r in results)
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Sakata · spreads</title><style>{CSS}</style></head><body>'
            f'<div class="wrap"><h1>Sakata · spread board</h1>'
            f'<div class="sub">generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC '
            f'· 18 instruments · outrights and pairs in one field</div>'
            f'<div class="tabs">{tabs}</div>{secs}'
            f'<div class="note faint" style="margin-top:20px">Rebuilt by GitHub '
            f'Actions. Yahoo rate-limits cloud IPs, so the data is fetched on a '
            f'runner and committed rather than pulled at page load.</div>'
            f'</div><script>{JS}</script></body></html>')


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true",
                    help="synthetic prices, no network")
    args = ap.parse_args()
    get = synth_closes if args.dry else fetch_closes

    print("fetching daily (2y)…")
    daily = get("1d", "2y")
    print("fetching hourly (60d)…")
    hourly = get("1h", "60d")
    if len(daily) < 2 and len(hourly) < 2:
        print("no price data, aborting")
        return 1

    results = []
    for p in PERIODS:
        r = build_period(p, daily, hourly)
        if r is None:
            print(f"  {p}: not enough data, skipped")
            continue
        print(f"  {p}: {r['bars']} bars, {r['instruments']} instruments, "
              f"SE ±{r['se']:.2f}")
        results.append(r)
    if not results:
        print("no periods built, aborting")
        return 1

    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(build_html(results), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print(f"wrote {OUT / 'index.html'} ({len(results)} periods)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
