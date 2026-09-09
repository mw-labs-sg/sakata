"""Sakata — the policy path the Fed Funds strip is pricing.

30-Day Fed Funds futures settle to the AVERAGE daily effective rate over their
contract month, so a single contract never prices a single rate: it prices a
weighted blend of whatever the target was before a meeting and whatever it
became after. Reading 100 minus the price as "the rate in October" is wrong in
exactly the months that matter, which are the ones with a meeting in them.

So the strip is inverted rather than read. Every month is one equation in the
unknown rates — the rate now, and the rate after each meeting — and the whole
system is solved at once by least squares. That is more robust than walking
the curve forward from a starting rate, which needs a starting rate this data
does not contain, and more robust than walking it backwards from the first
month without a meeting, which needs such a month to exist.

It also fails honestly. If the strip and the meeting calendar disagree, the
residual grows, and the residual ships with the answer.
"""
import calendar as _cal
import datetime as dt

import numpy as np

# Contract months to use. Beyond about a year and a half the contracts stop
# carrying open interest worth reading, and every extra month is another
# equation weighted the same as September's.
MAX_MONTHS = 18

# The size the committee moves in. Everything is quoted against it: a path
# implying 0.13% of easing is not a forecast of thirteen basis points, it is
# a coin flip between nothing and a cut.
STEP = 0.25

_MON = {m.upper(): i for i, m in enumerate(_cal.month_abbr) if m}


def parse_month(label: str):
    """'SEP 26' -> date(2026, 9, 1). None if it is not a month label."""
    try:
        mon, yr = str(label).strip().upper().split()
        y = int(yr)
        return dt.date(2000 + y if y < 100 else y, _MON[mon], 1)
    except Exception:
        return None


def _rate_index(day: dt.date, effective: list) -> int:
    """How many meetings have taken effect by `day`.

    A decision announced at 14:00 ET moves the target the FOLLOWING day, so a
    meeting on the 16th leaves the 16th itself at the old rate. Off by one here
    is off by a whole day's weight in a thirty-day average, which on a quarter
    point is worth about a basis point — small, and the wrong kind of small,
    since it biases every meeting the same way.
    """
    n = 0
    for e in effective:
        if day >= e:
            n += 1
    return n


def solve_path(months: list, meetings: list) -> dict:
    """Least-squares rates from monthly averages.

    `months` is [(first_of_month, implied_average_rate)], `meetings` the
    decision dates. Returns the rate now and the rate after each meeting.
    """
    eff = [m + dt.timedelta(days=1) for m in meetings]
    n_unk = len(meetings) + 1
    rows, rhs, used = [], [], []
    for first, avg in months:
        days = _cal.monthrange(first.year, first.month)[1]
        w = np.zeros(n_unk)
        for d in range(1, days + 1):
            w[_rate_index(dt.date(first.year, first.month, d), eff)] += 1.0 / days
        rows.append(w)
        rhs.append(avg)
        used.append(first)
    if not rows:
        return {}
    A, b = np.array(rows), np.array(rhs)
    # Columns with no weight anywhere are meetings the strip cannot see —
    # beyond its last contract. Solving for them would return whatever lstsq
    # finds least objectionable, so they are dropped and reported as unpriced
    # rather than answered with a number nobody can support.
    seen = A.sum(axis=0) > 1e-9
    x = np.full(n_unk, np.nan)
    sol, *_ = np.linalg.lstsq(A[:, seen], b, rcond=None)
    x[seen] = sol
    resid = float(np.max(np.abs(A[:, seen] @ sol - b))) if len(b) else 0.0
    return {"rates": x, "priced": seen, "resid": resid, "months": used}


def probabilities(delta: float) -> dict:
    """Split a priced change into the two nearest quarter-point outcomes.

    The strip prices an expectation, not an outcome, and an expectation of
    -13bp is not a forecast that the Fed will cut thirteen basis points. It is
    the market being about half convinced of a cut. Interpolating between the
    two nearest multiples of the step is the same reading CME publishes, and
    it is the only one the instrument supports.
    """
    if delta is None or delta != delta:
        return {}
    steps = delta / STEP
    lo, hi = int(np.floor(steps)), int(np.ceil(steps))
    if lo == hi:
        return {lo: 1.0}
    frac = steps - lo
    return {lo: 1.0 - frac, hi: frac}


def label_move(n: int) -> str:
    if n == 0:
        return "hold"
    size = abs(n) * int(STEP * 100)
    return f'{"hike" if n > 0 else "cut"} {size}'


def build_fomc(rows: list, meetings: list, trade_date: str = "") -> dict:
    """The Fed Funds strip, the path it implies, and the odds on each meeting."""
    today = dt.date.today()
    strip = []
    for r in rows:
        first = parse_month(r.get("month"))
        s = r.get("settle")
        if first is None or s is None:
            continue
        if first < dt.date(today.year, today.month, 1):
            continue                       # already expired into settlement
        strip.append({"month": r["month"], "first": first,
                      "settle": float(s), "implied": round(100 - float(s), 4),
                      "oi": r.get("oi"), "vol": r.get("vol")})
    strip.sort(key=lambda x: x["first"])
    # Stop at the last meeting we know about, plus the month after it. The
    # committee meets eight times a year and the calendar here lists them only
    # as far as it has been told; every month past the last one is an average
    # over meetings this code cannot see, and the solver can only explain it
    # by bending the rates it CAN see. Left in, eight such months dragged the
    # worst monthly residual to 3.7bp — an error the size of the thing being
    # measured.
    known = [m if isinstance(m, dt.date) else dt.date.fromisoformat(m)
             for m in meetings]
    if known:
        last = max(known)
        cutoff = dt.date(last.year + (last.month == 12),
                         last.month % 12 + 1, 1)
        strip = [s for s in strip if s["first"] <= cutoff]
    strip = strip[:MAX_MONTHS]
    if not strip:
        return {"meetings": [], "strip": [], "tradeDate": trade_date}

    horizon = strip[-1]["first"]
    meets = [dt.date.fromisoformat(m) if isinstance(m, str) else m
             for m in meetings]
    meets = sorted(m for m in meets if today <= m <= horizon)

    sol = solve_path([(s["first"], s["implied"]) for s in strip], meets)
    if not sol:
        return {"meetings": [], "strip": strip, "tradeDate": trade_date}

    rates, priced = sol["rates"], sol["priced"]
    now = float(rates[0]) if priced[0] else None
    out = []
    prev = now
    for i, m in enumerate(meets, start=1):
        r = float(rates[i]) if priced[i] else None
        step = (r - prev) if (r is not None and prev is not None) else None
        cum = (r - now) if (r is not None and now is not None) else None
        probs = probabilities(step)
        best = max(probs, key=probs.get) if probs else None
        out.append({
            "date": m.isoformat(),
            "days": (m - today).days,
            "rate": round(r, 4) if r is not None else None,
            "stepBp": round(step * 100, 1) if step is not None else None,
            "cumBp": round(cum * 100, 1) if cum is not None else None,
            "probs": {str(k): round(v * 100, 1) for k, v in probs.items()},
            "call": label_move(best) if best is not None else None,
            "callPct": round(probs[best] * 100, 1) if best is not None else None,
        })
        if r is not None:
            prev = r
    return {"now": round(now, 4) if now is not None else None,
            "meetings": out, "strip": strip, "tradeDate": trade_date,
            "resid": round(sol["resid"] * 100, 2), "step": STEP}
