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


def _rsi(df, period=14):
    """Wilder's RSI (1978) on daily closes.

    Included on request. Worth knowing what it is and is not: RSI measures
    direction, not risk, so it answers a different question from every other
    column here. It uses Wilder's smoothing — an EMA with alpha = 1/period —
    rather than a simple mean, which is what distinguishes real RSI from the
    approximations that circulate.
    """
    if df is None or len(df) < period + 5:
        return None
    d = df["close"].diff().dropna()
    if len(d) < period + 1:
        return None
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    last_dn = float(dn.iloc[-1])
    if last_dn == 0:
        return 100.0
    rs = float(up.iloc[-1]) / last_dn
    return float(100 - 100 / (1 + rs))


def _atr_series(df, window=20):
    """Rolling ATR as a series, so it can be ranked against its own history.

    Same windows as RV — 20 and 100 — rather than the conventional 14. The
    point of this tab is comparing the two measures, and a 14-day ATR beside a
    20-day vol invites the reader to attribute a difference to the market when
    it is really a difference in lookback.
    """
    if df is None or len(df) < window + 5:
        return None
    hi, lo, cl = df["high"], df["low"], df["close"]
    pc = cl.shift(1)
    tr = pd.concat([(hi - lo), (hi - pc).abs(), (lo - pc).abs()],
                   axis=1).max(axis=1)
    return tr.rolling(window).mean().dropna()


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


def _zscore(series) -> float:
    """How far the latest reading sits from its own mean, in sigmas.

    Taken on LOG volatility, not raw. Vol is bounded below at zero with a long
    right tail, so a z-score on the raw series is biased and over-reports
    extremes — which is precisely why the volatility literature models log-vol
    rather than vol. Logging first makes the distribution roughly normal and
    the sigma count mean what it says.

    This is the column the percentile cannot give you. A percentile saturates:
    two contracts both reading 100 might be +1.8σ and +4σ, and only one of
    those is a genuine dislocation.
    """
    if series is None or len(series) < 60:
        return None
    tail = series.tail(PCTILE_WIN)
    tail = tail[tail > 0]
    if len(tail) < 60:
        return None
    lg = np.log(tail)
    sd = float(lg.std())
    if sd == 0:
        return None
    return float((float(lg.iloc[-1]) - float(lg.mean())) / sd)


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
        volz = _zscore(fast)

        # ATR in points, then in dollars. The dollar figure is what actually
        # tells you anything: a 0.5 move in NG and a 5-point move in ES are
        # incomparable until the multiplier is applied.
        a_fast = _atr_series(df, VOL_WIN)
        a_slow = _atr_series(df, VOL_SLOW)
        atr = float(a_fast.iloc[-1]) if a_fast is not None and len(a_fast) else None
        atr100 = float(a_slow.iloc[-1]) if a_slow is not None and len(a_slow) else None
        atr_pct = _pctile(a_fast)
        atr_z = _zscore(a_fast)
        drange = atr * mult if (atr and mult) else None
        drange100 = atr100 * mult if (atr100 and mult) else None

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
            "volPct": _r(pct, 0), "volZ": _r(volz, 1),
            "atr": _r(drange, 0), "atr100": _r(drange100, 0),
            "atrPct": _r(atr_pct, 0), "atrZ": _r(atr_z, 1),
            "rsi": _r(_rsi(df), 0),
            # 20d over 100d: above 1.0 means the fast measure has pulled away
            # from its own base rate, which is the setup that precedes a hike
            # rather than follows it.
            "volTrend": _r(vol / vol100, 2) if (vol and vol100) else None,
            "margVol": _r(mpct / vol, 2) if (mpct and vol) else None,
            "daysATR": _r(maint / drange, 2) if (maint and drange) else None,
            "src": "AMP" if maint else "—",
        })
    return {"rows": rows}
