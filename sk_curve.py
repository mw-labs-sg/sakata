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
