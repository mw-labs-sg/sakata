"""Sakata — the Portfolio search, walked forward.

The Portfolio tab fits one basket to one window and reports what that basket
did over the window it was fitted to. Held forward answers half the obvious
objection by keeping the last 30% back, but it is still ONE fit and ONE
holdout, which is a sample of size one: a good number there can be the
window, and a bad one can be the fortnight.

This walks the same search along the window. At every rebalance the basket is
refitted on everything that had happened by then and held, untouched, until
the next one. The returns of those held segments are chained end to end, so
the curve it draws was never fitted to any of the data it is drawn on.

What that buys is the one number the Portfolio tab cannot produce: the gap
between what a fit scores on its own window and what the same recipe scores
out of sample. A search that beats equal weight by 180% in sample and loses
to it out of sample has not found a portfolio, it has found the window — and
until this tab existed there was no way to see that from inside Sakata.

Rebalance names are calendar names rather than bar counts, matching Sanpo's
Portfolio tab. "Every 21 bars" means a different thing on each of the nine
time frames; "Monthly" means the same thing on all of them.
"""
from collections import OrderedDict

import numpy as np
import pandas as pd

import sakata_stats as ss
import sk_portfolio as PF

# Cadences, and the period each one groups the index by. "H" is not a pandas
# frequency — half-years are derived in _period_key — and None is the single
# fit that never rebalances, which is the control the other five are read
# against rather than a cadence of its own.
REBALANCE = OrderedDict([
    ("No Rebalance", None),
    ("Weekly", "W"),
    ("Monthly", "M"),
    ("Quarterly", "Q"),
    ("Semi-Annual", "H"),
    ("Annual", "Y"),
])

# Bars the first fit must have before it is allowed to trade. A basket fitted
# to eleven bars is not a basket, and letting one through would put the
# worst-informed fit of the run at the front of the curve where it compounds
# through everything after it.
MIN_TRAIN = 24
WARMUP_FRAC = 0.25      # or this share of the window, whichever is larger
MIN_TEST = 2            # bars a segment must hold for its returns to count
MIN_SEGMENTS = 2        # below this it is a holdout, not a walk-forward


def _period_key(index: pd.DatetimeIndex, freq: str) -> list:
    """The calendar bucket each bar falls in.

    Half-years are built here rather than asked of pandas, which has no such
    period. Quarters would do it — (quarter - 1) // 2 — but going through the
    month is one step instead of two and reads as what it is.
    """
    if freq == "H":
        return [(t.year, (t.month - 1) // 6) for t in index]
    return list(index.to_period(freq))


def segments(index: pd.DatetimeIndex, cadence: str) -> list:
    """[(fit_upto, hold_from, hold_to)] in CLOSES positions.

    fit_upto is exclusive: the search sees closes[:fit_upto] and nothing
    after, which is the whole point. hold_from is the same bar, so the first
    return the basket earns is the step out of the last bar it was fitted on
    — no gap, and no bar counted twice.

    Returned before anything is run so the tab can say how many searches a
    cadence is about to cost. A Weekly walk over a year is fifty fits, and
    that is worth knowing before the click rather than during it.
    """
    n = len(index)
    if n < MIN_TRAIN + MIN_TEST:
        return []
    warm = max(MIN_TRAIN, int(n * WARMUP_FRAC))
    if n - warm < MIN_TEST:
        return []
    freq = REBALANCE.get(cadence)
    if freq is None:
        return [(warm, warm, n)]
    key = _period_key(index, freq)
    # Where a new calendar period starts, kept only once past the warm-up.
    marks = [i for i in range(1, n) if key[i] != key[i - 1] and i >= warm]
    if not marks:
        return []
    cuts = [warm] + [m for m in marks if m > warm]
    out = []
    for a, b in zip(cuts, cuts[1:] + [n]):
        if b - a >= MIN_TEST:
            out.append((a, a, b))
    return out


def _fine_slice(fine, index, a: int, b: int):
    """The fine bars that fall inside closes positions [a, b).

    Half-open on the left and closed on the right, so consecutive segments
    neither share a bar nor leave a gap between them — the same seam the
    coarse returns are cut on.
    """
    if fine is None or not len(fine):
        return None
    lo, hi = index[a], index[min(b, len(index) - 1)]
    f = fine[(fine.index > lo) & (fine.index <= hi)]
    return f if len(f) >= 2 else None


def walk_forward(closes, fine, objective: str = "ROA",
                 cadence: str = "Monthly", progress=None, **kw) -> dict:
    """Refit at every rebalance, hold to the next, chain what was held.

    `kw` is passed straight to optimise — max_legs, max_weight, side,
    risk_cap — so the walk tests the search the Portfolio tab actually ships
    rather than a reduced copy of it. That is also why it is slow: every
    segment is a full search, and there is no honest shortcut, because a
    cheaper search out of sample would be measuring a strategy the tab does
    not offer.
    """
    if closes is None or len(closes) < MIN_TRAIN + MIN_TEST:
        return {}
    segs = segments(closes.index, cadence)
    if not segs:
        return {}

    syms = list(closes.columns)
    # One return matrix, sliced by position. R row i is the step from
    # closes row i to row i+1, so a basket fitted on closes[:a] earns R[a-1]
    # first — the step out of the last bar it saw.
    R = closes.pct_change().iloc[1:]
    chained, chained_idx, fine_chained = [], [], []
    rows, prev_w = [], None
    total = len(segs) + 1           # the segments, plus the in-sample fit

    for k, (fit_upto, hold_from, hold_to) in enumerate(segs):
        if progress:
            progress(k, total, None)
        train = closes.iloc[:fit_upto]
        tf = fine[fine.index <= train.index[-1]] if fine is not None else None
        if tf is not None and len(tf) < 5:
            tf = None
        res = PF.optimise(train, tf, objective, **kw)
        if not res or not res.get("w"):
            continue
        w = np.array(res["w"], dtype=float)
        if len(w) != len(syms):
            continue
        seg_r = R.iloc[hold_from - 1:hold_to - 1]
        if len(seg_r) < MIN_TEST:
            continue
        r = seg_r.to_numpy() @ w
        chained.append(r)
        chained_idx.append(seg_r.index)
        fs = _fine_slice(fine, closes.index, hold_from, hold_to)
        if fs is not None:
            fine_chained.append(fs.pct_change().dropna().to_numpy() @ w)
        turn = PF.turnover(res["weights"], prev_w) if prev_w else {}
        prev_w = res["weights"]
        rows.append({
            "n": len(rows) + 1,
            "from": closes.index[hold_from].strftime("%d %b %y"),
            "to": closes.index[min(hold_to, len(closes) - 1)].strftime("%d %b %y"),
            "trainBars": int(fit_upto), "testBars": int(len(r)),
            "tot": round(float(np.prod(1 + r) - 1) * 100, 2),
            "legs": res["legs"],
            "label": " ".join(f'{x["code"]}{x["w"]:+.0f}'
                              for x in res["weights"][:4]),
            "weights": [{"code": x["code"], "w": x["w"]}
                        for x in res["weights"]],
            "turnover": turn.get("turnover"),
            "kept": turn.get("kept"),
        })

    if len(rows) < MIN_SEGMENTS and cadence != "No Rebalance":
        return {"short": True, "segments": len(rows),
                "cadence": cadence, "bars": len(closes)}
    if not chained:
        return {}

    r_all = np.concatenate(chained)
    idx_all = chained_idx[0].append(chained_idx[1:]) if len(chained_idx) > 1 \
        else chained_idx[0]
    rf_all = np.concatenate(fine_chained) if fine_chained else None
    oos = PF.stats_of(r_all, idx_all, rf_all)

    # The same search over the whole window, which is what the Portfolio tab
    # shows. It is the in-sample number the walk is read against, and it has
    # to be computed here rather than borrowed from that tab: the tab's is
    # quoted at the leverage on its screen, and this one must not be.
    if progress:
        progress(len(segs), total, None)
    full = PF.optimise(closes, fine, objective, **kw)
    ins = full.get("stats") if full else None

    # Equal weight over every instrument the walk ever held, carried the whole
    # way. The benchmark has to span the same bars as the thing it benchmarks,
    # so it starts where the walk starts rather than where the data does.
    held = [c["code"] for row in rows for c in row["weights"]]
    eq_stats, eq_curve = None, None
    if held:
        codes = sorted(set(held))
        want = [s for s in syms if ss.name_of(s) in codes]
        if want:
            cols = [syms.index(s) for s in want]
            ew = np.zeros(len(syms))
            ew[cols] = 1.0 / len(cols)
            start = segs[0][1] - 1
            eq_r = R.iloc[start:len(R)].to_numpy() @ ew
            eq_idx = R.index[start:len(R)]
            fs = _fine_slice(fine, closes.index, segs[0][1], len(closes))
            eq_rf = (fs.pct_change().dropna().to_numpy() @ ew
                     if fs is not None else None)
            eq_stats = PF.stats_of(eq_r, eq_idx, eq_rf)
            eq_curve = PF._series(eq_idx, eq_r)

    # How often each instrument survived a refit. This is the column the tab
    # exists for: a leg picked once in nine searches is the window talking, a
    # leg picked in eight is the only thing here that looks like a finding.
    persist = {}
    for row in rows:
        for c in row["weights"]:
            e = persist.setdefault(c["code"], {"code": c["code"], "n": 0,
                                               "sum": 0.0, "long": 0})
            e["n"] += 1
            e["sum"] += c["w"]
            e["long"] += 1 if c["w"] >= 0 else 0
    stability = sorted(
        ({"code": e["code"], "n": e["n"], "of": len(rows),
          "hit": round(e["n"] / len(rows) * 100),
          "avgW": round(e["sum"] / e["n"], 1),
          "side": ("long" if e["long"] == e["n"] else
                   "short" if e["long"] == 0 else "both")}
         for e in persist.values()),
        key=lambda x: (-x["n"], -abs(x["avgW"])))

    turns = [r["turnover"] for r in rows if r["turnover"] is not None]
    okey = {"ROA": "roa", "ER (Adj)": "erAdj", "Sharpe": "sharpe"}.get(
        objective, "roa")
    ov, iv = oos.get(okey), (ins or {}).get(okey)
    return {
        "cadence": cadence, "objective": objective, "okey": okey,
        "segments": rows, "nSegments": len(rows),
        "oos": oos, "inSample": ins, "equal": eq_stats,
        "curve": PF._series(idx_all, r_all),
        "equalCurve": eq_curve,
        "stability": stability,
        "bars": int(len(r_all)), "windowBars": int(len(closes)),
        "warmup": int(segs[0][0]),
        "start": idx_all[0].strftime("%d %b %y"),
        "end": idx_all[-1].strftime("%d %b %y"),
        "avgTurnover": round(float(np.mean(turns)), 1) if turns else None,
        "fitness": ov, "inSampleFitness": iv,
        # The headline. Negative means the recipe kept less out of sample than
        # it promised in it, which is the normal result and the useful one.
        "decay": (None if ov is None or not iv else
                  round((ov - iv) / abs(iv) * 100, 1)),
    }
