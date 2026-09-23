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

# How much history each refit is allowed to see. Labelled in BARS rather than
# borrowing the Time frame's day-names, because a lookback is counted in the
# window's own bars and those are not days on every window: "240D" over a
# 15-minute Intraday frame would be 240 prints, or about two sessions. Bars
# is also the unit the refit table already prints under Train.
#
# ROLLING is the default and Sanpo's choice, and it is the right one here for
# a reason particular to this tab: Time frame IS a lookback in live use. Pick
# 240D on Portfolio and you are fitting the last 240 days, so a walk that
# trains on an expanding window is testing a recipe the tab does not offer.
# It also keeps the refits comparable — anchored over Full means the first fit
# sees two years and the last sees nine, which are two different estimators
# chained into one curve — and it lets the basket forget a regime that ended.
#
# Anchored survives as an option because the argument for it is real: more
# data is less estimation noise, and that wins wherever the relationships
# actually are stable.
ANCHORED = "Anchored"
LOOKBACKS = OrderedDict([
    ("30 bars", 30), ("60 bars", 60), ("120 bars", 120), ("240 bars", 240),
    ("504 bars", 504), ("756 bars", 756), (ANCHORED, None),
])

# Bars the first fit must have before it is allowed to trade. A basket fitted
# to eleven bars is not a basket, and letting one through would put the
# worst-informed fit of the run at the front of the curve, where it compounds
# through everything after it.
MIN_TRAIN = 24
WARMUP_FRAC = 0.25      # anchored only: the share of the window kept as warm-up
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


def segments(index: pd.DatetimeIndex, cadence: str,
             lookback: str = ANCHORED) -> list:
    """[(train_from, fit_upto, hold_to)] in CLOSES positions.

    fit_upto is exclusive and is also where the holding starts: the search
    sees closes[train_from:fit_upto] and nothing after, and the first return
    the basket earns is the step out of the last bar it was fitted on — no
    gap, and no bar counted twice.

    train_from is 0 when anchored and fit_upto minus the lookback when
    rolling, which is the only difference between the two modes.

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
    back = LOOKBACKS.get(lookback, None)
    # Rolling warms up for exactly its lookback: a 240-bar training set does
    # not exist until there are 240 bars behind it, and starting earlier on a
    # short slice would be the anchored behaviour wearing a rolling label.
    warm = back if back else max(MIN_TRAIN, int(n * WARMUP_FRAC))
    if warm < MIN_TRAIN or n - warm < MIN_TEST:
        return []
    key = _period_key(index, freq)
    marks = [i for i in range(1, n) if key[i] != key[i - 1] and i >= warm]
    if not marks:
        return []
    cuts = [warm] + [m for m in marks if m > warm]
    out = []
    for a, b in zip(cuts, cuts[1:] + [n]):
        if b - a >= MIN_TEST:
            out.append((max(0, a - back) if back else 0, a, b))
    return out


# Seconds one refit costs on the nineteen, measured: 11s over 120 training
# bars, 10s over 240, 11s over 500, 16s over 1,000, 20s over 2,000. Flat plus
# a little per bar, because the pair screen is 171 scorings whatever the
# window and the slope is those scorings getting longer.
#
# This exists to price a run BEFORE it starts. The first version of the
# caption assumed five seconds a refit, which is roughly right for a year of
# daily bars and wrong by a factor of three over nine years — it told a
# reader seven minutes for a walk that takes twenty-two.
REFIT_FLAT = 10.0
REFIT_PER_BAR = 0.005


def cost_estimate(index, cadence: str, lookback: str = ANCHORED) -> tuple:
    """(refits, seconds) for a walk that has not run yet.

    Counts the whole-window fit at the end, because the reader is waiting for
    that too, and under a rolling lookback it is the most expensive single
    search in the run by some margin — every other fit is capped at the
    lookback and that one sees everything.
    """
    segs = segments(index, cadence, lookback)
    if not segs:
        return 0, 0.0
    trains = [b - a for a, b, _ in segs] + [len(index)]
    return len(segs), sum(REFIT_FLAT + REFIT_PER_BAR * t for t in trains)


def sweep_plan(index, cadences, lookbacks) -> tuple:
    """(cells, unique fits, seconds) for a grid that has not run yet.

    Counts the fits the way the run will: one per distinct (lookback, bar),
    because the cache collapses the rest. Without that the estimate would be
    a sum of walks and a sweep would look more expensive than it is.
    """
    want, cells = set(), 0
    for cad in cadences:
        for lb in lookbacks:
            segs = segments(index, cad, lb)
            if len(segs) < MIN_SEGMENTS:
                continue
            cells += 1
            for a, fit_upto, _ in segs:
                want.add((lb, fit_upto, fit_upto - a))
    if not cells:
        return 0, 0, 0.0
    secs = sum(REFIT_FLAT + REFIT_PER_BAR * t for _, _, t in want)
    # The whole-window fit is shared by every cell, so it is paid once.
    secs += REFIT_FLAT + REFIT_PER_BAR * len(index)
    return cells, len(want) + 1, secs


def sweep(closes, fine, objective: str = "ROA", cadences=(), lookbacks=(),
          progress=None, **kw) -> dict:
    """Walk every (cadence, lookback) pair and rank them out of sample.

    One shared fit cache across the grid, which is where the saving is: the
    coarse cadences rebalance on bars the fine ones have already fitted at
    the same lookback, and the whole-window fit is common to all of them.

    The winner keeps its full walk — curve, refits, leg stability — because
    it has already been computed and a grid that made you re-run the best
    cell to see it would be asking for the same minutes twice.
    """
    cache, grid, best, best_v = {}, [], None, None
    combos = [(c, lb) for c in cadences for lb in lookbacks
              if len(segments(closes.index, c, lb)) >= MIN_SEGMENTS]
    if not combos:
        return {}
    okey = {"ROA": "roa", "ER (Adj)": "erAdj", "Sharpe": "sharpe"}.get(
        objective, "roa")
    for i, (cad, lb) in enumerate(combos):
        if progress:
            progress(i, len(combos), f"{cad} / {lb}")
        r = walk_forward(closes, fine, objective, cad, lookback=lb,
                         fit_cache=cache, **kw)
        if not r or r.get("short") or not r.get("oos"):
            continue
        v = r["oos"].get(okey)
        grid.append({
            "cadence": cad, "lookback": lb, "n": r["nSegments"],
            "fitness": v, "tot": r["oos"].get("tot"),
            "mdd": r["oos"].get("mdd"), "sharpe": r["oos"].get("sharpe"),
            "vol": r["oos"].get("vol"), "decay": r.get("decay"),
            "fees": r.get("fees"), "turnover": r.get("avgTurnover"),
        })
        if v is not None and (best_v is None or v > best_v):
            best, best_v = r, v
    if not grid:
        return {}
    return {"grid": grid, "best": best, "okey": okey, "objective": objective,
            "cadences": [c for c in cadences
                         if any(g["cadence"] == c for g in grid)],
            "lookbacks": [lb for lb in lookbacks
                          if any(g["lookback"] == lb for g in grid)],
            "fits": len(cache), "cells": len(grid)}


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
                 cadence: str = "Monthly", lookback: str = ANCHORED,
                 capital: float = 1_000_000.0,
                 vol_target=30.0, max_lev=1.0, fees: dict = None,
                 fee_tier: float = 1.0, mult: dict = None,
                 progress=None, fit_cache: dict = None, **kw) -> dict:
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
    segs = segments(closes.index, cadence, lookback)
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

    for k, (train_from, fit_upto, hold_to) in enumerate(segs):
        hold_from = fit_upto
        if progress:
            progress(k, total, None)
        train = closes.iloc[train_from:fit_upto]
        # Bounded at BOTH ends now. Cutting only the right-hand side would
        # have handed a rolling fit the whole history on its fine bars, which
        # is the lookahead-free half of the mistake but still the wrong
        # training set.
        tf = None
        if fine is not None:
            tf = fine[(fine.index >= train.index[0])
                      & (fine.index <= train.index[-1])]
            if len(tf) < 5:
                tf = None
        # A fit is decided by the bars it sees and nothing else, so two walks
        # that rebalance on the same bar with the same lookback want the same
        # search. Across a sweep that is worth real minutes: the coarse
        # cadences land on bars the fine ones already fitted.
        ck = (lookback, fit_upto)
        res = fit_cache.get(ck) if fit_cache is not None else None
        if res is None:
            res = PF.optimise(train, tf, objective, **kw)
            if fit_cache is not None and res and res.get("w"):
                fit_cache[ck] = res
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
            "trainBars": int(fit_upto - train_from), "testBars": int(len(r)),
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
    fk = ("__full__", len(closes))
    full = fit_cache.get(fk) if fit_cache is not None else None
    if full is None:
        full = PF.optimise(closes, fine, objective, **kw)
        if fit_cache is not None and full:
            fit_cache[fk] = full
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
        "lookback": lookback,
        "warmup": int(segs[0][1]),
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
