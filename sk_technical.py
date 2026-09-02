"""Sakata — Range Levels across the five-rung ladder.

Prior segment high and low, the midpoint, the two retrace bands, and a bias
built from three independent votes: where price sits in the prior range,
which side of the retrace bands it is on, and the moving-average stack. The
votes are summed, not averaged, so the score carries how MANY agree.
"""
import numpy as np
import pandas as pd

import sk_universe as U
from sk_fmt import r as _r

MA1, MA2 = 100, 200


MIN_SEG_FRACTION = 0.4   # a segment must carry this share of the median bar
                         # count to count as a prior segment


def _prior(agg: pd.Series, sizes: pd.Series) -> pd.Series:
    """Previous SUBSTANTIVE segment's value, per segment.

    Calendar grouping does not know about weekends. On the Day rung the bars are
    hourly, so Sunday is its own period carrying the two hours of Sunday-evening
    globex — measured: 2 bars and a 4.75-point ES range against 33-74 on a
    weekday. A plain .shift(1) made that sliver Monday's "prior day", which put
    position at -263% of the prior range, suppressed reward:risk for want of a
    sane denominator, and dragged the Day bias vote to -1 while every other rung
    on the ladder read +1 to +3.

    So thin segments are dropped before the shift and their neighbours reach
    past them. Threshold is relative to the median rather than absolute because
    the same function serves five rungs whose segments hold wildly different bar
    counts, from ~23 hourly bars in a day to ~13 weekly bars in a quarter.
    """
    keep = sizes >= max(sizes.median() * MIN_SEG_FRACTION, 2)
    if not keep.any():
        return agg.shift(1)
    # Shift over surviving segments only, then carry each value forward across
    # the dropped ones so a thin segment still reports the last real range.
    return agg.where(keep).shift(1).ffill()


def levels(df: pd.DataFrame, seg: str) -> pd.DataFrame:
    """Range Levels: prior segment high/low, mid, and the RB/RS retrace bands."""
    o = df.copy()
    o["seg"] = o.index.to_period(seg)
    g = o.groupby("seg", sort=True)
    sizes = g.size()
    o["cur_high"] = g["high"].cummax()
    o["cur_low"] = g["low"].cummin()
    o["prev_high"] = o["seg"].map(_prior(g["high"].max(), sizes))
    o["prev_low"] = o["seg"].map(_prior(g["low"].min(), sizes))
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
    # ma100Side/ma200Side, NOT ma100/ma200: build_technical ships the numeric
    # levels under those names and spreads this dict over them, so naming the
    # side the same thing silently replaced two prices with the words "above"
    # and "below" — which the Levels table then rendered as an em dash.
    #
    # None stays None rather than collapsing to "below". A moving average that
    # has not enough history to exist is not the same statement as price being
    # under it, and reporting the second for the first is just wrong.
    def side(v):
        return None if v is None else ("above" if v else "below")

    return {"regime": regime, "retrace": retrace, "trend": trend,
            "ma100Side": side(a100), "ma200Side": side(a200),
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
    """{code: {horizon: {...levels, bias}}} across the whole ladder.

    No OHLC series ride along. They existed for a drill-down candle chart on
    the Technical tab; that chart is gone, and shipping a hundred bars across
    five fields for nineteen instruments on five rungs cost the grid real time
    and memory to build something nothing read.
    """
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
            per_h[h] = {
                "note": cfg["note"], "bar": cfg["bar"],
                "close": _r(r.close, 6), "chg": _r(chg, 2),
                "high": _r(r.prev_high, 6), "low": _r(r.prev_low, 6),
                "mid": _r(r.mid, 6), "rb": _r(r.rb, 6), "rs": _r(r.rs, 6),
                "ma100": _r(r.ma1, 6), "ma200": _r(r.ma2, 6),
                "pos": _r(r.pos, 1),
                "rngpct": _r((r.prev_high - r.prev_low) / r.prev_low * 100, 2),
                **read_bias(r), **read_rr(r),
            }
        if per_h:
            out[code] = per_h
    if missing:
        print(f"    technical gaps: {len(missing)} (e.g. {missing[:4]})")
    return {"grid": out, "order": U.LADDER_ORDER}
