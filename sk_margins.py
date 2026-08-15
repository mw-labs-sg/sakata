"""Sakata — margin against notional, realised vol, and where that vol sits.

The cushion view: what the exchange asks for, against what the contract is
actually worth, how far it moves in a day, and — the addition — whether
today's volatility is high or low for this contract rather than in absolute
terms. A 22% reading means nothing on its own; 22% at the 91st percentile of
its own year means the exchange is looking at the margin file.

Annualisation is measured off the index rather than assumed. BTC and ETH come
from Yahoo as 24/7 spot with roughly 365 bars a year, so the usual sqrt(252)
understated their vol by about 20% — the two rows most likely to move, wrong
in the direction that made them look calm.
"""
import numpy as np
import pandas as pd

import sk_universe as U
from sk_fmt import r as _r

VOL_WIN = 20        # the vol measure itself: one trading month
VOL_SLOW = 100      # the base rate: roughly five months, a full regime
PCTILE_WIN = 252    # one year of daily observations to rank against


def _bars_per_year(index) -> float:
    """Measured, not assumed. 252 for exchange-traded, ~365 for 24/7 crypto."""
    if len(index) < 30:
        return 252.0
    yrs = (index[-1] - index[0]).total_seconds() / (365.25 * 24 * 3600)
    if yrs <= 0:
        return 252.0
    return float(np.clip(len(index) / yrs, 12, 400))


def _atr(df, period=14):
    if df is None or len(df) < period + 1:
        return None
    hi, lo, cl = df["high"], df["low"], df["close"]
    pc = cl.shift(1)
    tr = pd.concat([(hi - lo), (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _vol_series(df, window):
    """Rolling annualised vol, as a series so it can be ranked against itself."""
    if df is None or len(df) < window + 5:
        return None
    r = df["close"].pct_change().dropna()
    if len(r) < window + 2:
        return None
    ann = _bars_per_year(r.index) ** 0.5
    return (r.rolling(window).std() * ann * 100).dropna()


def _pctile(series) -> float:
    """Where the latest reading sits in the trailing year of the same measure.

    The windows overlap, so a year of daily observations is nearer twelve
    independent samples than 252. That is enough to separate calm from
    stressed, which is all this column claims to do — it is not a p-value.
    """
    if series is None or len(series) < 60:
        return None
    tail = series.tail(PCTILE_WIN)
    return float((tail <= tail.iloc[-1]).mean() * 100)


def build_margins(margins: dict, daily: dict) -> dict:
    rows = []
    for code in U.CODES:
        m = margins.get(code) or {}
        maint = m.get("maint")
        df = daily.get(code)
        last = float(df["close"].iloc[-1]) if df is not None and len(df) else None
        mult = U.MULT.get(code)
        notl = last * mult if (last and mult) else None
        mpct = (maint / notl * 100) if (maint and notl) else None

        fast = _vol_series(df, VOL_WIN)
        slow = _vol_series(df, VOL_SLOW)
        vol = float(fast.iloc[-1]) if fast is not None and len(fast) else None
        vol100 = float(slow.iloc[-1]) if slow is not None and len(slow) else None
        pct = _pctile(fast)

        atr = _atr(df)
        drange = atr * mult if (atr and mult) else None
        rows.append({
            "code": code, "name": U.NAME[code], "sector": U.SECTOR[code],
            "group": U.GROUP_OF[U.SECTOR[code]], "dec": U.DEC[code],
            # Last and multiplier ship alongside notional so the arithmetic is
            # checkable on screen. A notional that looks wrong is usually a
            # multiplier problem, and without the price you cannot tell.
            "last": _r(last, 6), "mult": mult,
            "maint": _r(maint, 0), "day": _r(m.get("day"), 0),
            "notional": _r(notl, 0), "marginPct": _r(mpct, 2),
            "annVol": _r(vol, 1), "vol100": _r(vol100, 1),
            "volPct": _r(pct, 0),
            # 20d over 100d: above 1.0 means the fast measure has pulled away
            # from its own base rate, which is the setup that precedes a hike
            # rather than follows it.
            "volTrend": _r(vol / vol100, 2) if (vol and vol100) else None,
            "margVol": _r(mpct / vol, 2) if (mpct and vol) else None,
            "daysATR": _r(maint / drange, 2) if (maint and drange) else None,
            "src": "AMP" if maint else "—",
        })
    return {"rows": rows}
