"""Sakata — Range Levels across the five-rung ladder.

Prior segment high and low, the midpoint, the two retrace bands, and a bias
built from three independent votes: where price sits in the prior range,
which side of the retrace bands it is on, and the moving-average stack. The
votes are summed, not averaged, so the score carries how MANY agree.
"""
import numpy as np
import pandas as pd

import sk_universe as U
from sk_fmt import r as _r, sig as _sig

MA1, MA2 = 100, 200
DETAIL_BARS = 100       # bars of level history shipped per instrument/horizon


def levels(df: pd.DataFrame, seg: str) -> pd.DataFrame:
    """Range Levels: prior segment high/low, mid, and the RB/RS retrace bands."""
    o = df.copy()
    o["seg"] = o.index.to_period(seg)
    g = o.groupby("seg", sort=True)
    o["cur_high"] = g["high"].cummax()
    o["cur_low"] = g["low"].cummin()
    o["prev_high"] = o["seg"].map(g["high"].max().shift(1))
    o["prev_low"] = o["seg"].map(g["low"].min().shift(1))
    o["mid"] = (o.prev_high + o.prev_low) / 2
    o["rb"] = (o.cur_high + o.prev_low) / 2
    o["rs"] = (o.cur_low + o.prev_high) / 2
    o["ma1"] = o.close.rolling(MA1).mean()
    o["ma2"] = o.close.rolling(MA2).mean()
    o["pos"] = (o.close - o.prev_low) / (o.prev_high - o.prev_low) * 100
    return o.dropna(subset=["prev_high"])


def read_bias(r) -> dict:
    """Three independent votes — range, retrace, trend — summed to -3..+3."""
    if r.pos > 100:
        regime, s_rng = "Breakout", 1
    elif r.pos < 0:
        regime, s_rng = "Breakdown", -1
    else:
        regime, s_rng = "Range", 0
    hi, lo = max(r.rb, r.rs), min(r.rb, r.rs)
    if r.close > hi:
        retrace, s_ret = "Bull", 1
    elif r.close < lo:
        retrace, s_ret = "Bear", -1
    else:
        retrace, s_ret = "Neutral", 0
    a100 = r.close > r.ma1 if np.isfinite(r.ma1) else None
    a200 = r.close > r.ma2 if np.isfinite(r.ma2) else None
    if a100 and a200:
        trend, s_ma = "Bull", 1
    elif a100 is False and a200 is False:
        trend, s_ma = "Bear", -1
    else:
        trend, s_ma = "Neutral", 0
    score = s_rng + s_ret + s_ma
    bias = {3: "Strong Long", 2: "Long", 1: "Long tilt", 0: "Neutral",
            -1: "Short tilt", -2: "Short", -3: "Strong Short"}[score]
    return {"regime": regime, "retrace": retrace, "trend": trend,
            "ma100": "above" if a100 else "below",
            "ma200": "above" if a200 else "below",
            "score": score, "bias": bias}


def read_rr(r) -> dict:
    """Reward:risk to the retrace band and to the full prior range."""
    if not (0 <= r.pos <= 100):
        return {"stop": None, "target": None, "rr_retrace": None, "rr_range": None}
    px = r.close
    lo, hi = min(r.rb, r.rs), max(r.rb, r.rs)
    rr_r = (hi - px) / (px - lo) if (px > lo and hi > px) else None
    rr_g = ((r.prev_high - px) / (px - r.prev_low)
            if (px > r.prev_low and r.prev_high > px) else None)
    return {"stop": _r(lo, 6), "target": _r(hi, 6),
            "rr_retrace": _r(rr_r, 2), "rr_range": _r(rr_g, 2)}


def build_technical(frames_by_bar: dict) -> dict:
    """{code: {horizon: {...levels, bias, series}}} across the whole ladder."""
    out, missing = {}, []
    for code in U.CODES:
        per_h = {}
        for h in U.LADDER_ORDER:
            cfg = U.LADDER[h]
            df = frames_by_bar.get(cfg["bar"], {}).get(code)
            if df is None or len(df) < MA2 + 5:
                missing.append(f"{code}/{h}")
                continue
            o = levels(df, cfg["seg"])
            if o.empty:
                continue
            r = o.iloc[-1]
            chg = ((o.close.iloc[-1] / o.close.iloc[-2] - 1) * 100
                   if len(o) >= 2 else None)
            tail = o.tail(DETAIL_BARS)
            per_h[h] = {
                "note": cfg["note"], "bar": cfg["bar"],
                "close": _r(r.close, 6), "chg": _r(chg, 2),
                "high": _r(r.prev_high, 6), "low": _r(r.prev_low, 6),
                "mid": _r(r.mid, 6), "rb": _r(r.rb, 6), "rs": _r(r.rs, 6),
                "ma100": _r(r.ma1, 6), "ma200": _r(r.ma2, 6),
                "pos": _r(r.pos, 1),
                "rngpct": _r((r.prev_high - r.prev_low) / r.prev_low * 100, 2),
                **read_bias(r), **read_rr(r),
                # compact series for the drill-down chart: one array per field
                "t": [d.strftime("%Y-%m-%d %H:%M") for d in tail.index],
                "o": [_sig(v) for v in tail.open],
                "h": [_sig(v) for v in tail.high],
                "l": [_sig(v) for v in tail.low],
                "c": [_sig(v) for v in tail.close],
                "ph": [_sig(v) for v in tail.prev_high],
                "pl": [_sig(v) for v in tail.prev_low],
                "md": [_sig(v) for v in tail.mid],
                "vb": [_sig(v) for v in tail.rb],
                "vs": [_sig(v) for v in tail.rs],
            }
        if per_h:
            out[code] = per_h
    if missing:
        print(f"    technical gaps: {len(missing)} (e.g. {missing[:4]})")
    return {"grid": out, "order": U.LADDER_ORDER}
