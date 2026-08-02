"""Sakata — the spread field, one ranked table per calendar period.

Wraps sakata_stats (unchanged) so the statistics stay in one place. The only
thing done here is wiring the universe in, slicing by period, and shaping the
result for JSON.
"""
import datetime as dt

import numpy as np
import pandas as pd

import sakata_stats as ss
import sk_universe as U

PERIODS = ["WTD", "MTD", "QTD", "YTD"]
MODE = "vol"            # vol-adjusted legs; equal notional lets the loud leg win
RATIO_CAP = 5.0         # above this the sizing is not executable
TOP_N = 30

# Point sakata_stats at the live universe so NKD and anything added later flows
# through without editing two files.
ss.ALL_SYMBOLS = list(U.TICKERS)
ss.SYMBOL_NAMES = {U.TICKER[c]: c for c in U.CODES}
ss.SYMBOL_SECTOR = {U.TICKER[c]: U.SECTOR[c] for c in U.CODES}


def _resample(frames, bar):
    rule = {"1h": None, "4h": "4h", "1d": "1D", "1wk": "W-MON"}[bar]
    if rule is None:
        return frames
    return {k: v.resample(rule).last().dropna() for k, v in frames.items()}


def _period_field(period, daily_close, hourly_close):
    bar = ss.PERIOD_BARS[period]
    src = hourly_close if bar in ("1h", "4h") else daily_close
    start = pd.Timestamp(ss.period_start(period))
    frames = {k: v[v.index >= start] for k, v in src.items()}
    frames = {k: v for k, v in frames.items() if len(v) >= 5}
    if len(frames) < 2:
        return None
    frames = _resample(frames, bar)
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
    lg, sh = ss.leg_frequency(field, 20)

    def num(v, n=2):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if not np.isfinite(f) else round(f, n)

    rows = []
    for i, c in enumerate(field[:TOP_N], 1):
        rows.append({
            "n": i, "kind": c["kind"],
            "long": ss.name_of(c["long"]) if c["long"] else None,
            "short": ss.name_of(c["short"]) if c["short"] else None,
            "sector": str(c["Sector"]),
            "score": num(c["_score"], 1), "sharpe": num(c["Sharpe"]),
            "er": num(c["ER"], 3), "win": num(c["Win%"], 0),
            "tot": num(c["Tot%"], 1), "vol": num(c["Vol%"], 1),
            "mdd": num(c["MDD%"], 1), "corr": num(c["Corr"]),
            "ratio": num(c["Ratio"]),
        })

    return {
        "period": period, "bar": bar, "barName": ss.BAR_NAMES[bar],
        "bars": len(data), "instruments": len(data.columns),
        "span": span, "total": total, "pct": round(span / total, 3),
        "ends": end.strftime("%d %b"), "ann": round(ann),
        "se": round(ss.sharpe_se(span), 2), "seEnd": round(ss.sharpe_se(total), 2),
        "noise": round(ss.sharpe_se(span) * 2.8, 1),
        "nOut": len(outs), "nPair": len(pairs), "nCapped": n_capped,
        "nField": len(field),
        "dropped": [ss.name_of(d) for d in dropped],
        "medOut": num(np.median([c["Sharpe"] for c in outs])) if outs else 0,
        "medPair": num(np.median([c["Sharpe"] for c in pairs])) if pairs else 0,
        "bestOut": ss.pos_label(best_out) if best_out else None,
        "bestPair": ss.pos_label(best_pair) if best_pair else None,
        "legShort": [[ss.name_of(k), v] for k, v in sh.most_common(6)],
        "legLong": [[ss.name_of(k), v] for k, v in lg.most_common(6)],
        "rows": rows,
    }


def build_spreads(daily: dict, hourly: dict) -> dict:
    """daily/hourly are {code: OHLC frame}; only closes are used here."""
    dclose = {U.TICKER[c]: df["close"].dropna() for c, df in daily.items()
              if df is not None and len(df)}
    hclose = {U.TICKER[c]: df["close"].dropna() for c, df in hourly.items()
              if df is not None and len(df)}
    out = {}
    for p in PERIODS:
        try:
            r = _period_field(p, dclose, hclose)
        except Exception as e:
            print(f"    spreads {p} failed: {str(e)[:70]}")
            r = None
        if r is None:
            print(f"    spreads {p}: not enough data")
            continue
        print(f"    spreads {p}: {r['bars']} bars, {r['instruments']} instruments, "
              f"SE +/-{r['se']}")
        out[p] = r
    return {"periods": PERIODS, "mode": MODE, "cap": RATIO_CAP,
            "topN": TOP_N, "data": out}
