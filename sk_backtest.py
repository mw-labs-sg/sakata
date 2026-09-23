"""Sakata — the Portfolio search, walked forward.

Portfolio fits one basket to one window and reports what that basket did over
the window it was fitted to. Held forward answers half the obvious objection
by keeping the last 30% back, but it is ONE fit and ONE holdout, which is a
sample of size one: a good number there can be the window, and a bad one can
be the fortnight.

This walks the same search along the window. At every rebalance the basket is
refitted on everything that had happened by then and held, untouched, until
the next one. The returns of those held segments are chained end to end, so
the curve it draws was never fitted to any of the data it is drawn on.

Two things make the numbers comparable to the rest of the Portfolio tab
rather than merely adjacent to it:

Every refit is SIZED the way the tab sizes — each basket levered to the vol
target using the volatility it showed on its own training window, capped by
Max leverage. Sizing on the test window's volatility would be a forecast made
with the answer in hand; sizing at unit gross would put a 1x curve under a 5x
table, which is the disagreement this tab exists to avoid.

And every rebalance is CHARGED. Turnover has been running above half the
basket a month, which at nineteen contracts and a retail schedule is not a
rounding error. Fees come from the same table the ticket column uses, priced
at the rebalance bar, so the cost of a cadence is the cost the account would
have paid rather than a plausible-looking constant.

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
# frequency — half-years are derived in _period_key.
#
# There is deliberately no "no rebalance" entry. On the merged tab that choice
# is "Full period", which is not a cadence at all but the single whole-window
# fit the tab has always done, and it is answered before this module is
# reached. An unknown cadence returns no segments rather than quietly falling
# back to a holdout.
REBALANCE = OrderedDict([
    # Daily is here for the three windows whose bars are finer than a day.
    # Intraday is 15-minute prints over three sessions and WTD is hourly
    # since Monday: on those, every calendar cadence coarser than this one
    # spans the whole window and there is nothing to walk. On a daily-bar
    # window it means a refit every bar, which is honest but slow, and the
    # tab prices it before the click rather than after.
    ("Daily", "D"),
    ("Weekly", "W"),
    ("Monthly", "M"),
    ("Quarterly", "Q"),
    ("Semi-Annual", "H"),
    ("Annual", "Y"),
])

# Bars the first fit must have before it is allowed to trade. A basket fitted
# to eleven bars is not a basket, and letting one through would put the
# worst-informed fit of the run at the front of the curve, where it compounds
# through everything after it.
MIN_TRAIN = 24
WARMUP_FRAC = 0.25      # or this share of the window, whichever is larger
# One bar is a real holding period, not a degenerate one: a daily rebalance
# on a daily-bar window holds each basket for exactly one bar, and that is the
# strategy rather than a rounding error in it. The chain does not care how
# long a segment is, only that the weights were fixed across it.
MIN_TEST = 1            # bars a segment must hold for its returns to count
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
    freq = REBALANCE.get(cadence)
    if freq is None:
        return []
    warm = max(MIN_TRAIN, int(n * WARMUP_FRAC))
    if n - warm < MIN_TEST:
        return []
    key = _period_key(index, freq)
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


def _leverage(vol: float, vol_target, max_lev) -> float:
    """What the tab would have sized this basket at, knowing only its past.

    Same rule plan() uses: the vol target over the basket's own volatility,
    held under the cap. `vol` is the TRAINING window's volatility, because
    that is the only one that had happened when the position went on.
    """
    if vol_target is None:
        want = max_lev or 1.0
    else:
        want = (vol_target / vol) if vol and vol > 0 else 0.0
    return min(want, max_lev) if max_lev else want


def _contracts(w, lev, capital, prices, codes, mult) -> np.ndarray:
    """Contracts each leg holds, fractional and signed.

    Fractional on purpose. Rounding to whole lots is a real cost and the
    Portfolio tab measures it — that is what the Miss column is — but doing
    it here would mix two effects in one number, and the one this tab is
    asking about is the cadence. A tenth of a contract of ES is also not the
    error that decides whether a monthly rebalance pays for itself.
    """
    out = np.zeros(len(w))
    for i, code in enumerate(codes):
        unit = prices[i] * (mult.get(code) or 0)
        if unit:
            out[i] = w[i] * lev * capital / unit
    return out


def _fee_for(delta: np.ndarray, codes, fees: dict, tier: float) -> float:
    """Dollars to move from one contract vector to another.

    Half a round turn per contract traded, not a whole one. The table is
    quoted round-turn — in and out — so a leg that opens here and closes at
    some later rebalance is charged half at each end and one round turn in
    total, which is what it costs. Charging the full figure on every change
    would bill the account twice for one trade.
    """
    tot = 0.0
    for i, code in enumerate(codes):
        rt = (fees or {}).get(code, (0.0, 0.0))[0] or 0.0
        tot += abs(float(delta[i])) * rt / 2 * tier
    return tot


def walk_forward(closes, fine, objective: str = "ROA",
                 cadence: str = "Monthly", capital: float = 1_000_000.0,
                 vol_target=30.0, max_lev=1.0, fees: dict = None,
                 fee_tier: float = 1.0, mult: dict = None,
                 progress=None, **kw) -> dict:
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
    codes = [ss.name_of(s) for s in syms]
    mult = mult or {}
    R = closes.pct_change().iloc[1:]
    px = closes.to_numpy()

    gross, net, idx_parts, fine_parts = [], [], [], []
    rows, prev_w, held = [], None, np.zeros(len(syms))
    fee_total = 0.0
    total = len(segs) + 1           # the segments, plus the whole-window fit

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

        # Levered on what the TRAINING window showed, never the test window.
        lev = _leverage((res.get("stats") or {}).get("vol") or 0.0,
                        vol_target, max_lev)
        r = (seg_r.to_numpy() @ w) * lev

        # The trade into this basket, priced at the bar it goes on.
        want = _contracts(w, lev, capital, px[hold_from], codes, mult)
        fee = _fee_for(want - held, codes, fees, fee_tier)
        fee_total += fee
        held = want
        # The cost lands on the first bar it was incurred on rather than
        # being smeared across the segment. It is a ticket, not a carry.
        r_net = r.copy()
        if capital:
            r_net[0] -= fee / capital

        gross.append(r)
        net.append(r_net)
        idx_parts.append(seg_r.index)
        fs = _fine_slice(fine, closes.index, hold_from, hold_to)
        if fs is not None:
            fine_parts.append((fs.pct_change().dropna().to_numpy() @ w) * lev)

        turn = PF.turnover(res["weights"], prev_w) if prev_w else {}
        prev_w = res["weights"]
        rows.append({
            "n": len(rows) + 1,
            "from": closes.index[hold_from].strftime("%d %b %y"),
            "to": closes.index[min(hold_to, len(closes) - 1)].strftime("%d %b %y"),
            "trainBars": int(fit_upto), "testBars": int(len(r)),
            "lev": round(float(lev), 2),
            "fee": round(float(fee), 0),
            "tot": round(float(np.prod(1 + r_net) - 1) * 100, 2),
            "legs": res["legs"],
            "label": " ".join(f'{x["code"]}{x["w"]:+.0f}'
                              for x in res["weights"][:4]),
            "weights": [{"code": x["code"], "w": x["w"]}
                        for x in res["weights"]],
            "turnover": turn.get("turnover"),
        })

    if len(rows) < MIN_SEGMENTS:
        return {"short": True, "segments": len(rows),
                "cadence": cadence, "bars": len(closes)}
    if not gross:
        return {}

    # Closing the book at the end of the window. Every contract still on goes
    # off, and it costs what it costs — a walk that never pays to get out is
    # quoting a position it is still holding as a result it banked.
    exit_fee = _fee_for(-held, codes, fees, fee_tier)
    fee_total += exit_fee
    if capital and len(net[-1]):
        net[-1] = net[-1].copy()
        net[-1][-1] -= exit_fee / capital

    r_gross, r_net = np.concatenate(gross), np.concatenate(net)
    idx_all = (idx_parts[0].append(idx_parts[1:]) if len(idx_parts) > 1
               else idx_parts[0])
    rf_all = np.concatenate(fine_parts) if fine_parts else None
    oos_gross = PF.stats_of(r_gross, idx_all, rf_all)
    # The fine series carries no fees, so the net drawdown is measured on the
    # coarse bars. Quoting the gross hole beside a net return would flatter
    # the ratio that divides one by the other.
    oos = PF.stats_of(r_net, idx_all)

    # The same search over the whole window: the basket you would hold NOW,
    # since it is the only fit that has seen every bar. The walk beside it is
    # how much of its score to believe.
    if progress:
        progress(len(segs), total, None)
    full = PF.optimise(closes, fine, objective, **kw)
    ins = None
    if full and full.get("stats"):
        flev = _leverage(full["stats"].get("vol") or 0.0, vol_target, max_lev)
        fw = np.array(full["w"], dtype=float)
        # Through _Scorer, not stats_of: this row is the same basket the card
        # above it is quoting, so it has to be measured the same way —
        # including a drawdown taken off the fine bars. Two MDDs for one
        # portfolio, eight rows apart, is the kind of disagreement a reader
        # cannot see and cannot unsee.
        ins = PF._Scorer(closes, fine).stats(fw * flev)

    # Equal weight over every instrument the walk ever held, carried the whole
    # way and sized by the same rule, so the benchmark is not quietly running
    # at a different exposure from the thing it benchmarks.
    eq_stats, eq_curve = None, None
    ever = sorted({c["code"] for row in rows for c in row["weights"]})
    cols = [i for i, c in enumerate(codes) if c in ever]
    if cols:
        ew = np.zeros(len(syms))
        ew[cols] = 1.0 / len(cols)
        start = segs[0][1] - 1
        eq_r = R.iloc[start:].to_numpy() @ ew
        eq_idx = R.index[start:]
        elev = _leverage(float(eq_r.std()) * ss.ann_factor_for(eq_idx) ** 0.5
                         * 100, vol_target, max_lev)
        eq_stats = PF.stats_of(eq_r * elev, eq_idx)
        eq_curve = PF._series(eq_idx, eq_r * elev)

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
    levs = [r["lev"] for r in rows]
    okey = {"ROA": "roa", "ER (Adj)": "erAdj", "Sharpe": "sharpe"}.get(
        objective, "roa")
    ov, iv = oos.get(okey), (ins or {}).get(okey)
    tot_net = oos.get("tot") or 0.0
    return {
        "cadence": cadence, "objective": objective, "okey": okey,
        "segments": rows, "nSegments": len(rows),
        "oos": oos, "oosGross": oos_gross, "inSample": ins, "equal": eq_stats,
        "curve": PF._series(idx_all, r_net),
        "grossCurve": PF._series(idx_all, r_gross),
        "equalCurve": eq_curve,
        "stability": stability,
        "full": full,
        "bars": int(len(r_net)), "windowBars": int(len(closes)),
        "warmup": int(segs[0][0]),
        "start": idx_all[0].strftime("%d %b %y"),
        "end": idx_all[-1].strftime("%d %b %y"),
        "avgTurnover": round(float(np.mean(turns)), 1) if turns else None,
        "avgLev": round(float(np.mean(levs)), 2) if levs else None,
        "capital": capital,
        "fees": round(float(fee_total), 0),
        "feeBps": round(fee_total / capital * 10_000, 1) if capital else None,
        # What the cadence cost as a share of what it made. The number that
        # answers "is rebalancing this often paying for itself".
        "feeShare": (round(fee_total / capital * 100 / abs(tot_net) * 100, 1)
                     if capital and tot_net else None),
        "fitness": ov, "inSampleFitness": iv,
        # The headline. Negative means the recipe kept less out of sample than
        # it promised in it, which is the normal result and the useful one.
        "decay": (None if ov is None or not iv else
                  round((ov - iv) / abs(iv) * 100, 1)),
    }
