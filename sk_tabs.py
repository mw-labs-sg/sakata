"""Sakata — tab compute. Pure pandas/numpy, no network, no UI.

Everything here takes already-fetched frames and returns JSON-ready dicts. The
split matters: sources can fail and be retried, compute cannot fail differently
between the runner and a laptop.
"""
import datetime as dt

import numpy as np
import pandas as pd

import sk_universe as U

MA1, MA2 = 100, 200
DETAIL_BARS = 100       # bars of level history shipped per instrument/horizon


def _sig(v, digits=7):
    """Significant-figure rounding for the series arrays. Fixed decimals ship
    useless precision on BTC and useful precision on 6J; significant figures
    get both right and cut the payload roughly in half."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return float(f"{f:.{digits}g}")


def _r(v, n=4):
    """Round for JSON, mapping NaN/inf to None so JS gets null not a string."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, n)


# ------------------------------------------------------------------- board
def build_board(daily: dict) -> dict:
    """Last close plus Day/WTD/MTD/QTD/YTD from daily closes."""
    rows = []
    for code in U.CODES:
        df = daily.get(code)
        if df is None or df.empty:
            continue
        s = df["close"].dropna()
        if s.empty:
            continue
        pairs = [(d.date(), float(v)) for d, v in zip(s.index, s.values)]
        today, last = pairs[-1]

        def ref_before(boundary):
            r = None
            for d, v in pairs:
                if d < boundary:
                    r = v
                else:
                    break
            return r

        def pct(ref):
            return _r((last / ref - 1) * 100, 2) if ref else None

        wk = today - dt.timedelta(days=today.weekday())
        mo = today.replace(day=1)
        qt = dt.date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        yr = dt.date(today.year, 1, 1)
        rows.append({
            "code": code, "name": U.NAME[code], "sector": U.SECTOR[code],
            "group": U.GROUP_OF[U.SECTOR[code]], "dec": U.DEC[code],
            "last": _r(last, 6), "asof": str(today),
            "Day": _r((last / pairs[-2][1] - 1) * 100, 2) if len(pairs) > 1 else None,
            "WTD": pct(ref_before(wk)), "MTD": pct(ref_before(mo)),
            "QTD": pct(ref_before(qt)), "YTD": pct(ref_before(yr)),
        })
    return {"rows": rows}


# --------------------------------------------------------------- technical
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


# ------------------------------------------------------------------- curve
_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def _month_date(m):
    try:
        a, b = str(m).split()
        return dt.date(2000 + int(b), _MONTHS[a[:3].upper()], 1)
    except Exception:
        return None


def _months_between(d1, d2):
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def build_curve(raw: dict) -> dict:
    """Sort each curve by contract date and derive roll and annualised carry."""
    out = {}
    for code, rows in raw.get("curves", {}).items():
        clean = []
        for r in rows:
            d = _month_date(r["month"])
            if d is None or r.get("settle") is None:
                continue
            clean.append({**r, "_d": d.isoformat()})
        clean.sort(key=lambda x: x["_d"])
        if len(clean) < 2:
            continue
        front, back = clean[0]["settle"], clean[-1]["settle"]
        a, b = clean[0], clean[1]
        step = _months_between(dt.date.fromisoformat(a["_d"]),
                               dt.date.fromisoformat(b["_d"])) or 1
        span = _months_between(dt.date.fromisoformat(clean[0]["_d"]),
                               dt.date.fromisoformat(clean[-1]["_d"])) or 1
        roll = a["settle"] - b["settle"]
        roll_pct = roll / b["settle"] * 100 if b["settle"] else 0.0
        out[code] = {
            "code": code, "name": U.NAME[code], "sector": U.SECTOR[code],
            "rows": clean,
            "front": _r(front, 4), "back": _r(back, 4),
            "frontMonth": clean[0]["month"], "backMonth": clean[-1]["month"],
            "shape": ("Backwardation" if back < front else
                      "Contango" if back > front else "Flat"),
            "roll": _r(roll, 4), "rollPct": _r(roll_pct, 2),
            "rollAnn": _r(roll_pct * (12 / step), 2),
            "carryAnn": _r((front - back) / back * (12 / span) * 100
                           if back else 0.0, 2),
        }
    return {"tradeDate": raw.get("tradeDate"), "curves": out}


# ----------------------------------------------------------------- margins
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
