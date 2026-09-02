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

# How far past the prior edge an excursion must reach, as a share of the
# prior range, before giving it back counts as a FAILED break rather than
# noise. Measured without it on the Day rung: twelve of nineteen columns
# flagged a failure, because a session dipping a tick or two under
# yesterday's low and recovering is what most sessions do. At that rate
# the mark says nothing, and worse, it crowded out the band position it
# was drawn on top of. A tenth of the range is a move somebody had to
# mean; below that the close is the only thing worth reading.
MIN_POKE = 0.10


# Ranking the prior segment's range against the segments before it. An ATR
# in BARS would answer a different question from the one this tab asks: the
# levels are a segment's high and low, so the range that matters is the
# segment's, and the average to read it against is an average of segments.
# It also makes the reading follow the Horizon dropdown for free — prior day
# on Day, prior week on Week — instead of needing its own timeframe control.
SEG_RANK_WIN = 100      # completed segments to rank the prior one against,
                        # matching the Margin tab's slow window. Clamped to
                        # what a rung actually holds, which is 100 on Day
                        # and Week and about 24 and 40 on Month and Qtr.
SEG_RANK_MIN = 8        # below this a percentile is theatre, not a statistic
ATR_SEGS = 20           # segments in the average range


def _seg_ranges(df: pd.DataFrame, seg: str) -> pd.Series:
    """High-low of every COMPLETED segment, thin ones dropped.

    Same MIN_SEG_FRACTION filter _prior uses, for the same reason: two hours
    of Sunday globex is not a day, and letting it into the sample would put
    the bottom of the range distribution somewhere no session ever went.

    The segment in progress is dropped outright. It is not a range yet, and
    ranking a Monday morning against finished weeks reports the quietest week
    of the year — every week, until about Wednesday.
    """
    p = df.index.to_period(seg)
    g = df.groupby(p)
    sizes = g.size()
    keep = sizes >= max(sizes.median() * MIN_SEG_FRACTION, 2)
    rng = (g["high"].max() - g["low"].min())[keep].dropna()
    return rng[rng.index != p[-1]]


# Bars per year at each segment size, for annualising a vol computed on
# segment closes. A year rung is left out on purpose: one observation a year
# cannot be annualised, and printing a number there would be arithmetic
# rather than a measurement.
SEG_PER_YEAR = {"D": 252, "W": 52, "M": 12, "Q": 4}
HV_SEGS = 20            # the measure itself
HV_SLOW = 100           # the base rate beside it, as the Margin tab does


def read_hv(df: pd.DataFrame, seg: str) -> dict:
    """Annualised vol of segment-to-segment closes.

    Deliberately not the bar-level HV the Margin tab computes. That one
    annualises an hourly series with a factor clipped to 400 bars a year, so
    its LEVELS are badly understated and only its ranks are safe to read.
    Here the observations are the same units the rest of the row is in — one
    per day on Day, one per week on Week — so the number can be printed as a
    number.
    """
    p = df.index.to_period(seg)
    g = df.groupby(p)
    sizes = g.size()
    keep = sizes >= max(sizes.median() * MIN_SEG_FRACTION, 2)
    closes = g["close"].last()[keep]
    closes = closes[closes.index != p[-1]]
    ret = closes.pct_change().dropna()
    per_year = SEG_PER_YEAR.get(str(seg)[0].upper())
    if per_year is None or len(ret) < SEG_RANK_MIN:
        return {"segHv": None, "segHv100": None, "segHvPct": None, "segHvN": 0}
    # Rolled rather than taken once, so the level and its rank come off the
    # same series. A vol quoted beside a percentile computed some other way
    # is two answers to one question, and the reader has no way to see it.
    roll = ret.rolling(min(HV_SEGS, len(ret))).std().dropna()
    if roll.empty:
        return {"segHv": None, "segHv100": None, "segHvPct": None, "segHvN": 0}
    ann = per_year ** 0.5
    hv = float(roll.iloc[-1]) * ann * 100
    # The slow reading is the base rate the fast one is judged against, and it
    # is left blank rather than approximated when a rung has not got a hundred
    # segments. A "100-segment vol" computed over twenty-four is a different
    # measure wearing the same label, which is worse than an em dash.
    hv_slow = None
    if len(ret) >= HV_SLOW:
        hv_slow = float(ret.tail(HV_SLOW).std()) * ann * 100
    pct, n = None, 0
    if len(roll) >= SEG_RANK_MIN:
        tail = roll.tail(SEG_RANK_WIN)
        n = int(len(tail))
        pct = float((tail <= tail.iloc[-1]).mean() * 100)
    # The sample size ships with the rank because it is not always 52. A
    # Month rung built from two years of 4h bars has twenty-odd observations
    # and a Qtr rung forty, so their percentiles land on multiples of 4 and
    # 2.5 — still a rank, but one whose tooltip must not claim a year of
    # weeks it never had.
    return {"segHv": _r(hv, 1), "segHv100": _r(hv_slow, 1),
            "segHvPct": _r(pct, 0), "segHvN": n}


def read_range(rng: pd.Series) -> dict:
    """The prior segment's range, the average before it, and its percentile."""
    if rng is None or len(rng) < SEG_RANK_MIN + 1:
        return {"segRange": None, "segAtr": None, "segAtrN": ATR_SEGS,
                "segRangeX": None, "segRangePct": None, "segRangeN": 0}
    prior = float(rng.iloc[-1])
    tail = rng.tail(SEG_RANK_WIN)
    atr = float(rng.tail(ATR_SEGS).mean())
    return {
        "segRange": _r(prior, 6),
        "segAtr": _r(atr, 6),
        "segAtrN": ATR_SEGS,
        "segRangeX": _r(prior / atr, 2) if atr else None,
        "segRangePct": _r(float((tail <= prior).mean() * 100), 0),
        "segRangeN": int(len(tail)),
    }


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
    """Three independent votes — range, retrace, trend — summed to -3..+3,
    plus the one thing the sum cannot express: where in the structure the
    close actually is.
    """
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
    # Where price sits in the structure, which the score cannot carry. A sum
    # of three votes says how MANY agree and never WHICH, so a +1 through the
    # prior high read identically to a +1 drifting mid-range.
    #
    # cur_high and cur_low are the current segment's running extremes, so a
    # poke that has since been given back is visible here and nowhere else.
    # The score is right to call that Range — the break did not hold, and the
    # range vote is about the close — and equally right to be unable to say
    # it was a failure rather than a quiet day inside the range. Those are
    # not the same market, and on ES this week they were the whole story.
    span = r.prev_high - r.prev_low
    if span > 0:
        over = (r.cur_high - r.prev_high) / span
        under = (r.prev_low - r.cur_low) / span
    else:                       # a prior segment with no range at all
        over = under = 0.0
    poke_hi = over >= MIN_POKE
    poke_lo = under >= MIN_POKE
    if regime != "Range":
        structure = regime
    elif poke_hi and poke_lo:
        # An outside segment that took both ends. The bigger excursion is the
        # one that mattered; the smaller one it merely brushed.
        structure = "Failed breakout" if over >= under else "Failed breakdown"
    elif poke_hi:
        structure = "Failed breakout"
    elif poke_lo:
        structure = "Failed breakdown"
    elif retrace == "Bull":
        structure = "Above bands"
    elif retrace == "Bear":
        structure = "Below bands"
    else:
        structure = "Mid"

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

    return {"regime": regime, "structure": structure,
            "retrace": retrace, "trend": trend,
            "ma100Side": side(a100), "ma200Side": side(a200),
            "score": score, "bias": bias}


def read_bands(cur: pd.DataFrame, r) -> dict:
    """A band reached and given back — the two events these levels exist for.

    On CLOSES, never wicks. The obvious wick version marked 94% of the grid
    and no threshold fixed it: the bands are built FROM the segment's own
    extremes — rb is the midpoint of its high and the prior low, rs of its
    low and the prior high — so any segment whose range is anything like the
    one before it brackets both by construction. A level drawn inside your
    own range is not a level you can touch. A close beyond one that has since
    been given back is an event, and the earlier bars are the evidence while
    the current one is only the outcome.
    """
    blank = {"rsMark": None, "rbMark": None, "bandNote": None}
    if cur is None or len(cur) < 2:
        return blank
    # Against BOTH bands, not each one alone. rb and rs cross — a segment
    # that rallies hard drags rb up through rs — and read separately that
    # puts a cell above RS and below RB at the same time. Measured: nine
    # cells in ten carried a mark, which is a mark on none of them. max/min
    # is what the retrace vote already uses, for exactly this reason.
    past = cur["close"].iloc[:-1]
    hi = cur[["rb", "rs"]].max(axis=1).iloc[:-1]
    lo = cur[["rb", "rs"]].min(axis=1).iloc[:-1]
    now_hi, now_lo = max(r.rb, r.rs), min(r.rb, r.rs)
    # Only the give-back is reported. Still being beyond a band is what the
    # glyph says, and repeating it here spends a mark on a fact already on
    # the cell three characters to the left.
    rejected = bool((past > hi).any()) and r.close <= now_hi
    reclaimed = bool((past < lo).any()) and r.close >= now_lo
    said = []
    if rejected:
        said.append("rejected at RS")
    if reclaimed:
        said.append("reclaimed RB")
    return {"rsMark": "rejected" if rejected else None,
            "rbMark": "reclaimed" if reclaimed else None,
            "bandNote": " \u00b7 ".join(said) or None}


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
                **read_bands(o[o["seg"] == r.seg], r),
                **read_range(_seg_ranges(df, cfg["seg"])),
                **read_hv(df, cfg["seg"]),
            }
        if per_h:
            out[code] = per_h
    if missing:
        print(f"    technical gaps: {len(missing)} (e.g. {missing[:4]})")
    return {"grid": out, "order": U.LADDER_ORDER}
