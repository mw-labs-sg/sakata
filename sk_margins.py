"""Sakata — margin against notional, realised vol, and daily range.

The cushion view: what the exchange asks for, against what the contract is
actually worth and how far it moves in a day.
"""
import pandas as pd

import sk_universe as U
from sk_fmt import r as _r


def _atr(df, period=14):
    if df is None or len(df) < period + 1:
        return None
    hi, lo, cl = df["high"], df["low"], df["close"]
    pc = cl.shift(1)
    tr = pd.concat([(hi - lo), (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _ann_vol(df, window=20):
    if df is None or len(df) < window + 2:
        return None
    r = df["close"].pct_change().dropna()
    if len(r) < window:
        return None
    return float(r.tail(window).std() * (252 ** 0.5) * 100)


def build_margins(margins: dict, daily: dict) -> dict:
    """Margin against notional, realised vol and daily range — the cushion view."""
    rows = []
    for code in U.CODES:
        m = margins.get(code) or {}
        maint = m.get("maint")
        df = daily.get(code)
        last = float(df["close"].iloc[-1]) if df is not None and len(df) else None
        mult = U.MULT.get(code)
        notl = last * mult if (last and mult) else None
        mpct = (maint / notl * 100) if (maint and notl) else None
        vol = _ann_vol(df)
        atr = _atr(df)
        drange = atr * mult if (atr and mult) else None
        rows.append({
            "code": code, "name": U.NAME[code], "sector": U.SECTOR[code],
            "maint": _r(maint, 0), "day": _r(m.get("day"), 0),
            "notional": _r(notl, 0), "marginPct": _r(mpct, 2),
            "annVol": _r(vol, 1),
            "margVol": _r(mpct / vol, 2) if (mpct and vol) else None,
            "daysATR": _r(maint / drange, 2) if (maint and drange) else None,
            "src": "AMP" if maint else "—",
        })
    return {"rows": rows}
