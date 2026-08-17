"""Sakata — term structure, roll, and annualised carry from CME settlements."""
import datetime as dt

import sk_universe as U
from sk_fmt import r as _r


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


def _int(x):
    """CME ships volume and OI as formatted strings: '2,060,284' or ''."""
    try:
        return int(float(str(x).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


MIN_BACK_OI = 100        # absolute floor for a tradeable back month
MIN_BACK_OI_SHARE = 0.01  # ...or this share of the front month's OI


def _back_index(clean: list) -> int:
    """Index of the furthest contract with enough open interest to be real.

    The old rule took the last listed month unconditionally. CME lists ES out to
    SEP 31 and CL to the mid-2030s, and those tails settle at a model price with
    zero volume and zero open interest — live ES had OI 0 on fourteen of its
    twenty-one months. Annualised carry was therefore measured against a
    contract nobody holds, and because the listed tail length varies by product
    the scanner was ranking a five-year ES span against a nine-year CL one.

    A back month qualifies on max(100 lots, 1% of front OI): the absolute floor
    rejects the model-priced tail, the relative one stops a very deep book
    making its own far months look tradeable. Falls back to the last row so a
    product that reports no OI at all still gets a curve rather than vanishing.
    """
    front_oi = _int(clean[0].get("oi"))
    floor = max(MIN_BACK_OI, front_oi * MIN_BACK_OI_SHARE)
    for i in range(len(clean) - 1, 0, -1):
        if _int(clean[i].get("oi")) >= floor:
            return i
    return len(clean) - 1


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
        bi = _back_index(clean)
        front, back = clean[0]["settle"], clean[bi]["settle"]
        a, b = clean[0], clean[1]
        step = _months_between(dt.date.fromisoformat(a["_d"]),
                               dt.date.fromisoformat(b["_d"])) or 1
        span = _months_between(dt.date.fromisoformat(clean[0]["_d"]),
                               dt.date.fromisoformat(clean[bi]["_d"])) or 1
        roll = a["settle"] - b["settle"]
        roll_pct = roll / b["settle"] * 100 if b["settle"] else 0.0
        out[code] = {
            "code": code, "name": U.NAME[code], "sector": U.SECTOR[code],
            "rows": clean,
            "front": _r(front, 4), "back": _r(back, 4),
            "frontMonth": clean[0]["month"], "backMonth": clean[bi]["month"],
            # How far out the liquid curve actually reaches, so the scanner's
            # spans are comparable on screen rather than only in principle.
            "backOI": _int(clean[bi].get("oi")), "spanMonths": span,
            "listedMonths": len(clean),
            "shape": ("Backwardation" if back < front else
                      "Contango" if back > front else "Flat"),
            "roll": _r(roll, 4), "rollPct": _r(roll_pct, 2),
            "rollAnn": _r(roll_pct * (12 / step), 2),
            "carryAnn": _r((front - back) / back * (12 / span) * 100
                           if back else 0.0, 2),
        }
    return {"tradeDate": raw.get("tradeDate"), "curves": out}
