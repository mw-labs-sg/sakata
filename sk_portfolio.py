"""Sakata — weights for a basket, searched rather than solved.

The Trends tab ranks relationships one at a time. This asks the next question:
holding several of them at once, in what proportion. The objective is whichever
statistic the field is being read in — ROA, ER (Adj) or Sharpe — and two of
those three are path statistics, which is what decides the whole approach here.

Mean-variance has a closed form because its objective is a quadratic in the
weights. ER is |net move| over path length and ROA divides by the single worst
moment, so neither is a function of means and covariances at all: they depend
on the ORDER of the returns. There is no matrix to invert. What is left is
search, and the honest thing is to say so rather than to dress a hill climb up
as an optimisation.

Two consequences worth keeping in mind while reading the output:

  * The result is a good weight vector, not the best one. Restarts and a local
    climb find the neighbourhood; nothing here proves it is the global peak.
  * It is fitted in sample. On a 96-bar window with nineteen instruments to
    choose from, some of what it finds is this week's noise wearing a ratio.
    Constraints are the defence — few legs, capped weights — which is why they
    are arguments rather than options buried in a config.
"""
import numpy as np
import pandas as pd

import sakata_stats as ss

# The three the field can be ranked on. Win% and Tot% are deliberately absent:
# maximising Win% buys a hundred tiny gains and one ruinous loss, and maximising
# Tot% with shorts allowed just levers the best performer to the weight cap.
OBJECTIVES = ("ROA", "ER (Adj)", "Sharpe")

MIN_MDD = 0.05      # same floor the Trends tab uses, and for the same reason:
                    # a drawdown of nothing is not a denominator
MAX_ROA = 99.0

# Smalls allowed on top of whole standards before the fill is called good
# enough. Five covers half a standard where the small is a tenth of one.
TOPUP_SMALLS = 5

# How far a fill may land from its leg before it stops being that leg. The same
# 2% the spread tickets in sk_spreads hedge to, and for the same reason: past
# it you are holding a different position from the one that was ranked.
HEDGE_TOL = 2.0

# Refinement passes over the best basket found, after the restarts. Three is
# where the spread between seeds stopped shrinking on measurement.
POLISH_ROUNDS = 3

# Distinct starting points for the leg-swap pass. Three was where the spread
# between seeds stopped falling on measurement.
EXCHANGE_STARTS = 3

# Swaps that survive the unclimbed screen and get a real climb. Forty of a
# possible hundred and fifty-six: measured against twelve and twenty-four,
# forty was the first width at which the seed the tab actually uses found the
# best basket in all three windows rather than two of them. Climbing all
# hundred and fifty-six found no more and took three times as long.
SCREEN_KEEP = 40


def _drawdown(r: np.ndarray) -> float:
    """Worst peak-to-trough of the compounded series, anchored at 1.0."""
    cum = np.empty(len(r) + 1)
    cum[0] = 1.0
    np.cumprod(1 + r, out=cum[1:])
    peak = np.maximum.accumulate(cum)
    return float(((cum - peak) / peak).min() * 100)


def _efficiency(r: np.ndarray, obs) -> float:
    """ss.efficiency with the session mask lifted out of the loop.

    Same arithmetic, including the 1.0 anchor and the unobserved-gap mask —
    they are precomputed once per window here because this runs thousands of
    times per click rather than once per row.
    """
    cum = np.empty(len(r) + 1)
    cum[0] = 1.0
    np.cumprod(1 + r, out=cum[1:])
    d = np.diff(cum)
    if obs is not None:
        d = d[obs]
    path = np.abs(d).sum()
    if path == 0:
        return 0.0
    net = d.sum()
    return float(net / path)          # signed, like the original


class _Scorer:
    """Everything a weight vector is judged on, over one window."""

    def __init__(self, closes: pd.DataFrame, fine: pd.DataFrame | None):
        self.syms = list(closes.columns)
        rets = closes.pct_change().dropna()
        self.R = rets.to_numpy()
        self.index = rets.index
        self.bars = len(rets)
        self.root = self.bars ** 0.5
        self.ann = ss.ann_factor_for(rets.index)
        self.obs = ss._observed(rets.index)
        # Drawdown on the finest marks the window reaches, exactly as the
        # Trends tab measures it — a portfolio priced only at daily closes
        # steps over the same intraday holes a single spread does.
        if fine is not None and len(fine) > len(rets):
            f = fine.pct_change().dropna()
            self.Rf = f.to_numpy()
            self.fine_bars = len(f)
        else:
            self.Rf = self.R
            self.fine_bars = self.bars

    def curve(self, w: np.ndarray) -> np.ndarray:
        return self.R @ w

    def stats(self, w: np.ndarray) -> dict:
        r = self.R @ w
        er = _efficiency(r, self.obs)
        mdd = _drawdown(self.Rf @ w)
        tot = float(np.prod(1 + r) - 1) * 100
        sd = float(r.std())
        return {
            "er": round(er, 3), "erAdj": round(er * self.root, 2),
            "roa": (None if abs(mdd) < MIN_MDD else
                    round(float(np.clip(tot / abs(mdd), -MAX_ROA, MAX_ROA)), 1)),
            "sharpe": (0.0 if sd == 0 else
                       round(float(r.mean() / sd * self.ann ** 0.5), 2)),
            "tot": round(tot, 1), "mdd": round(mdd, 1),
            "vol": round(sd * self.ann ** 0.5 * 100, 1),
            "win": round(float((r > 0).mean() * 100)),
        }

    def risk_shares(self, w: np.ndarray) -> np.ndarray:
        """Each leg's share of portfolio variance, summing to 1.

        The weights are NOTIONAL — 20% of the risk budget in ETH is 20% of the
        money, not 20% of the risk, and ETH moves several times as much as ZN
        per dollar. This is the column that says which one you actually have.
        Contribution is w_i x cov(r_i, r_p) / var(r_p), the standard
        decomposition: it sums to one and a leg that hedges reads negative.
        """
        r = self.R @ w
        var = float(r.var())
        if var == 0:
            return np.zeros_like(w)
        cov = (self.R * (r - r.mean())[:, None]).mean(axis=0)
        return w * cov / var

    def risk_ok(self, w: np.ndarray, cap: float) -> bool:
        """True if no leg carries more than `cap` of the variance.

        A cap on WEIGHT does not cap risk: a basket can hold 10% of its money
        in ether and 52% of its variance there, because ether moves several
        times as much per dollar as a bond future. Capping the share of
        variance is the constraint that actually produces a diversified
        basket rather than one bet wearing five hedges.
        """
        if not cap:
            return True
        return float(np.abs(self.risk_shares(w)).max()) <= cap

    def score(self, w: np.ndarray, objective: str,
              risk_cap: float = 0.0) -> float:
        """One number, higher better. -inf for anything unrankable.

        Scored on the same definitions the stats report, with one extra
        condition on ROA. Ranking a table of pairs, a suspiciously small
        drawdown is a curiosity; SEARCHING for the largest ratio makes it the
        objective, and a hill climb will happily spend its whole budget
        shrinking the denominator. So a portfolio whose worst hole is smaller
        than one typical bar of its own movement is not scored: it did not
        avoid a drawdown, it was measured too coarsely to have had one.
        """
        if risk_cap and not self.risk_ok(w, risk_cap):
            return -np.inf
        r = self.R @ w
        if objective == "Sharpe":
            sd = float(r.std())
            return -np.inf if sd == 0 else float(r.mean() / sd)
        if objective == "ER (Adj)":
            return _efficiency(r, self.obs)     # root is constant per window
        rf = self.Rf @ w
        mdd = _drawdown(rf)
        floor = max(MIN_MDD, float(np.median(np.abs(rf))) * 100)
        if abs(mdd) < floor:
            return -np.inf
        return float(np.clip((np.prod(1 + r) - 1) * 100 / abs(mdd),
                             -MAX_ROA, MAX_ROA))


def _project(w: np.ndarray, max_legs: int, cap: float,
             allow_short: bool) -> np.ndarray:
    """Nearest weight vector obeying the constraints: legs, cap, gross of 1.

    Order matters. Trim to the largest legs first, then cap, then normalise —
    capping before trimming lets a leg that is about to be dropped absorb
    weight that the survivors then have to give back.
    """
    if not allow_short:
        w = np.clip(w, 0, None)
    if max_legs and np.count_nonzero(w) > max_legs:
        keep = np.argsort(-np.abs(w))[:max_legs]
        trimmed = np.zeros_like(w)
        trimmed[keep] = w[keep]
        w = trimmed
    gross = np.abs(w).sum()
    if gross == 0:
        return w
    w = w / gross
    if cap < 1:
        for _ in range(8):          # cap, renormalise, repeat: capping pushes
            w = np.clip(w, -cap, cap)   # weight onto the others, which can then
            gross = np.abs(w).sum()     # breach the cap themselves
            if gross == 0:
                return w
            w = w / gross
            if np.abs(w).max() <= cap + 1e-9:
                break
    return w


def _pairs(sc: _Scorer, objective: str, cap: float, allow_short: bool,
           keep: int = 6, risk_cap: float = 0.0) -> list:
    """Every two-instrument basket at the weight cap, best first.

    Exhaustive where exhaustive is cheap — 171 pairs by four sign combinations
    is nothing — and it gives the climb somewhere real to start. A random draw
    over nineteen instruments finds a good pair by luck; this finds the best
    one by construction, which turns "the search should beat its own best
    pair" from a hope into a floor.
    """
    n = len(sc.syms)
    signs = ((1, 1), (1, -1), (-1, 1), (-1, -1)) if allow_short else ((1, 1),)
    out = []
    for i in range(n):
        for j in range(i + 1, n):
            for si, sj in signs:
                w = np.zeros(n)
                w[i], w[j] = si * 0.5, sj * 0.5
                w = _project(w, 2, cap, allow_short)
                v = sc.score(w, objective, risk_cap)
                if np.isfinite(v):
                    out.append((v, w))
    out.sort(key=lambda t: -t[0])
    return out[:keep]


def _climb(sc: _Scorer, w0: np.ndarray, objective: str, max_legs: int,
           cap: float, allow_short: bool, rng, steps: int,
           risk_cap: float = 0.0) -> tuple:
    """Hill climb from w0: perturb, swap a leg, grow one, drop one.

    All four moves matter. Perturbation alone fixes the basket at whatever
    size it started; swapping alone fixes the count; growing without
    shrinking makes a ceiling of ten score worse than a ceiling of six.
    """
    n = len(sc.syms)
    best_w, best_v = w0, sc.score(w0, objective, risk_cap)
    step = 0.25
    for i in range(steps):
        cand = best_w.copy()
        roll = rng.random()
        held, idle = np.flatnonzero(cand), np.flatnonzero(cand == 0)
        if roll < 0.2 and len(held) and len(idle):
            out_, in_ = rng.choice(held), rng.choice(idle)
            cand[in_], cand[out_] = cand[out_], 0.0
        elif roll < 0.35 and len(idle) and len(held) < max_legs:
            cand[rng.choice(idle)] = (rng.choice([-1.0, 1.0]) if allow_short
                                      else 1.0) * float(np.abs(cand).mean())
        elif roll < 0.45 and len(held) > 2:
            cand[held[np.argmin(np.abs(cand[held]))]] = 0.0
        else:
            cand += rng.normal(0, step, n) * (np.abs(cand) > 0)
        cand = _project(cand, max_legs, cap, allow_short)
        v = sc.score(cand, objective, risk_cap)
        if v > best_v:
            best_w, best_v = cand, v
        if i % 60 == 59:
            step *= 0.7
    return best_w, best_v


def _grow(sc: _Scorer, w0: np.ndarray, objective: str, max_legs: int,
          cap: float, allow_short: bool, rng, steps: int = 150,
          risk_cap: float = 0.0) -> tuple:
    """Add legs one at a time, keeping whichever addition helps most.

    The restarts kept finding DIFFERENT leg sets — one seed built on NQ and
    ZN, another on ES and NKD, a third on NQ, BTC and ZB — and scoring ten
    points apart. A hill climb cannot cross between those: swapping one leg
    at a time walks downhill before it walks up, so each start stays in the
    basin it landed in. Trying every candidate leg explicitly is how that gets
    searched instead of sampled, and it is deterministic, which is most of
    why the answer stopped depending on the seed.

    Nineteen instruments by two signs by a short climb each, per level. Not
    cheap, and not optional: it is the difference between the tab returning
    the best basket it can find and returning one of them.
    """
    best_w, best_v = w0, sc.score(w0, objective, risk_cap)
    while np.count_nonzero(best_w) < max_legs:
        level_w, level_v = None, best_v
        base = float(np.abs(best_w[np.flatnonzero(best_w)]).mean())
        for idx in np.flatnonzero(best_w == 0):
            for sign in ((1.0, -1.0) if allow_short else (1.0,)):
                cand = best_w.copy()
                cand[idx] = sign * base
                cand = _project(cand, max_legs, cap, allow_short)
                cand, v = _climb(sc, cand, objective, max_legs, cap,
                                 allow_short, rng, steps, risk_cap)
                if v > level_v:
                    level_w, level_v = cand, v
        if level_w is None:      # nothing left to add that pays for itself
            break
        best_w, best_v = level_w, level_v
    return best_w, best_v


def _exchange(sc: _Scorer, w0: np.ndarray, objective: str, max_legs: int,
              cap: float, allow_short: bool, rng, rounds: int = 4,
              steps: int = 150, tick=None, risk_cap: float = 0.0) -> tuple:
    """Try replacing each held leg with each instrument not held.

    Growing a basket a leg at a time is myopic: it can never reach a set
    whose first two legs were not the pair it started from, which is exactly
    how one seed ended on NQ and ZN while another found ES and NKD ten points
    higher. This searches the 1-exchange neighbourhood — every held leg
    against every candidate — and repeats until a full pass finds nothing.

    Deterministic and exhaustive at that radius, which is what makes the
    answer stop being a property of the seed.
    """
    best_w, best_v = w0, sc.score(w0, objective, risk_cap)
    for _ in range(rounds):
        held, idle = np.flatnonzero(best_w), np.flatnonzero(best_w == 0)
        # Screen every swap unclimbed first. Climbing all of them cost 150
        # steps x 13 candidates x 2 signs x 6 legs — 23,000 evaluations to
        # rank a list, which is where the progress bar visibly stalled. The
        # raw score is a coarse ranking but a cheap one, and only the
        # plausible dozen need to be walked properly.
        screened = []
        for out_ in held:
            for in_ in idle:
                for sign in ((1.0, -1.0) if allow_short else (1.0,)):
                    cand = best_w.copy()
                    cand[in_] = sign * abs(cand[out_])
                    cand[out_] = 0.0
                    cand = _project(cand, max_legs, cap, allow_short)
                    screened.append((sc.score(cand, objective, risk_cap), cand))
        screened.sort(key=lambda t: -t[0])
        shortlist = []
        for _v, cand in screened[:SCREEN_KEEP]:
            cand, v = _climb(sc, cand, objective, max_legs, cap, allow_short,
                             rng, steps, risk_cap)
            shortlist.append((v, cand))
        # A swap arrives with the weights of the leg it replaced, so a short
        # climb judges it before it has had a chance to be itself. Re-climbing
        # the few best properly is what let ZN → BTC through: worse on 150
        # steps, better on 600, and worth six points of ROA.
        shortlist.sort(key=lambda t: -t[0])
        round_w, round_v = None, best_v
        for _v, cand in shortlist[:3]:
            cand, v = _climb(sc, cand, objective, max_legs, cap, allow_short,
                             rng, steps * 4, risk_cap)
            if v > round_v:
                round_w, round_v = cand, v
        if tick:
            tick()
        if round_w is None:
            break                      # a full pass improved nothing: stop
        best_w, best_v = round_w, round_v
    return best_w, best_v


def optimise(closes: pd.DataFrame, fine=None, objective: str = "ROA",
             max_legs: int = 4, max_weight: float = 0.5,
             allow_short: bool = True, tries: int = 1200,
             climbs: int = 900, restarts: int = 8, seed: int = 0,
             progress=None, risk_cap: float = 0.0) -> dict:
    """Search weights maximising `objective` over the window in `closes`.

    Restarts, then climbs, then the best pairs climbed as well.

    One random pass and one climb was a coin toss. Measured on a live WTD
    field, ten seeds of that search returned ROA between 29.4 and 38.9 for
    the same data, and the fixed seed landed near the bottom of the range —
    which is not a portfolio, it is a sample from one. Twelve independent
    restarts plus the exhaustive best pairs as further starting points close
    that spread to a point or so, and cost a couple of seconds.

    The seed is still fixed, so the answer does not wander between reruns.
    It is now fixed on something worth returning to rather than on whichever
    hill the first draw happened to land beside.

    `progress` is called as progress(done, total, best) if given: the search
    is long enough now to owe the reader a count.
    """
    if closes is None or closes.shape[1] < 2 or len(closes) < 10:
        return {}
    sc = _Scorer(closes, fine)
    n = len(sc.syms)
    max_legs = max(2, min(max_legs, n))
    seeds = _pairs(sc, objective, max_weight, allow_short,
                   risk_cap=risk_cap)
    # Four rounds apiece is the ceiling for the swap passes; they usually
    # stop earlier, so the bar can finish before the count does.
    total = (max(1, restarts) + 2 * len(seeds) + POLISH_ROUNDS
             + EXCHANGE_STARTS * 4 + 5)
    done = 0

    def tick(best):
        if progress:
            progress(done, total, None if best == -np.inf else best)

    best_w, best_v = None, -np.inf
    pool = []           # every stage's answer, not just the winning one
    tick(best_v)
    # Every restart is its own random pass and its own climb, from its own
    # seed. Independent starts beat one long climb on a surface this lumpy.
    for r in range(max(1, restarts)):
        rng = np.random.default_rng(seed * 1_000 + r)
        start_w, start_v = None, -np.inf
        for _ in range(tries):
            k = int(rng.integers(2, max_legs + 1))
            legs = rng.choice(n, size=k, replace=False)
            w = np.zeros(n)
            mag = rng.dirichlet(np.ones(k))
            w[legs] = mag * (rng.choice([-1.0, 1.0], size=k)
                             if allow_short else 1.0)
            w = _project(w, max_legs, max_weight, allow_short)
            v = sc.score(w, objective, risk_cap)
            if v > start_v:
                start_w, start_v = w, v
        if start_w is not None:
            w, v = _climb(sc, start_w, objective, max_legs, max_weight,
                          allow_short, rng, climbs, risk_cap)
            pool.append((v, w))
            if v > best_v:
                best_w, best_v = w, v
        done += 1
        tick(best_v)

    # And the best pairs, climbed like any other start. Whatever else the
    # search does, it cannot now return less than the best two instruments
    # on the board — the floor a random pass could only reach by luck.
    for i, (_v0, pw) in enumerate(seeds):
        rng = np.random.default_rng(seed * 1_000 + 900 + i)
        w, v = _climb(sc, pw, objective, max_legs, max_weight, allow_short,
                      rng, climbs, risk_cap)
        pool.append((v, w))
        if v > best_v:
            best_w, best_v = w, v
        done += 1
        tick(best_v)

    # Then grow each of those pairs a leg at a time, trying every candidate.
    # This is the part that actually searches leg SETS rather than sampling
    # them, and the part that made the answer stop depending on the seed.
    for i, (_v0, pw) in enumerate(seeds):
        rng = np.random.default_rng(seed * 1_000 + 700 + i)
        w, v = _grow(sc, pw, objective, max_legs, max_weight, allow_short, rng,
                 risk_cap=risk_cap)
        pool.append((v, w))
        if v > best_v:
            best_w, best_v = w, v
        done += 1
        tick(best_v)

    if best_w is None:
        return {}

    # Swap legs before polishing: the leg SET is the coarse decision and the
    # weights are the fine one, so searching sets while the weights are still
    # rough is the cheaper order.
    #
    # From the best FEW starts, not the single best. Exchange is a local
    # search over leg sets, so it inherits whichever basin it is handed —
    # run only from the incumbent, one seed reached 61 and another stalled at
    # 45 on the same data. Three starts costs three times as long and removes
    # most of what was left of the seed dependence.
    pool.sort(key=lambda t: -t[0])
    for i, (_pv, pw) in enumerate(pool[:EXCHANGE_STARTS]):
        rng = np.random.default_rng(seed * 1_000 + 400 + i)

        def _round():
            # The bar moves per ROUND inside the swap pass. Between stages was
            # fine when a stage was a second; it read as a hang once a stage
            # became eight.
            nonlocal done
            done += 1
            tick(best_v)

        w, v = _exchange(sc, pw, objective, max_legs, max_weight,
                         allow_short, rng, tick=_round, risk_cap=risk_cap)
        if v > best_v:
            best_w, best_v = w, v
        tick(best_v)

    # Polish. Restarts find the right hill; this walks the last stretch up it.
    # ROA on a 36-bar window is a spiky surface — the denominator is ONE bad
    # moment, so a small change in weights can move which moment that is —
    # and independent starts left a spread of ten points between seeds even
    # after twelve of them. Refining the incumbent, rather than yet another
    # random draw, is what closes that: same answer whichever start reached it.
    for i in range(POLISH_ROUNDS):
        rng = np.random.default_rng(seed * 1_000 + 500 + i)
        w, v = _climb(sc, best_w, objective, max_legs, max_weight, allow_short,
                      rng, climbs * 3, risk_cap)
        if v > best_v:
            best_w, best_v = w, v
        done += 1
        tick(best_v)

    # One more alternation. Polishing moves the weights, which can put a
    # different leg swap in reach; swapping moves the set, which gives the
    # polish somewhere new to go. Stopping after a single pass of each left
    # the seeds a tenth apart, and this is the cheap half of closing that.
    rng = np.random.default_rng(seed * 1_000 + 600)

    def _round2():
        nonlocal done
        done += 1
        tick(best_v)

    w, v = _exchange(sc, best_w, objective, max_legs, max_weight,
                     allow_short, rng, tick=_round2, risk_cap=risk_cap)
    if v > best_v:
        best_w, best_v = w, v
    w, v = _climb(sc, best_w, objective, max_legs, max_weight, allow_short,
                  rng, climbs * 3, risk_cap)
    if v > best_v:
        best_w, best_v = w, v
    done += 1
    tick(best_v)

    order = np.argsort(-np.abs(best_w))
    risk = sc.risk_shares(best_w)
    weights = [{"sym": sc.syms[i], "code": ss.name_of(sc.syms[i]),
                "w": round(float(best_w[i]) * 100, 1),
                "risk": round(float(risk[i]) * 100, 1)}
               for i in order if abs(best_w[i]) > 5e-4]

    # Equal weight over the same legs, as the thing the search has to beat. A
    # portfolio that cannot beat naive weighting on its own objective has found
    # nothing but a way to spend a click.
    eq = np.zeros(n)
    eq[np.flatnonzero(best_w)] = np.sign(best_w[np.flatnonzero(best_w)])
    eq = _project(eq, max_legs, 1.0, allow_short)

    return {
        "objective": objective, "weights": weights,
        "w": [float(x) for x in best_w], "equalW": [float(x) for x in eq],
        "syms": sc.syms,
        "stats": sc.stats(best_w), "equal": sc.stats(eq),
        "bars": sc.bars, "fineBars": sc.fine_bars,
        "legs": len(weights), "gross": round(float(np.abs(best_w).sum()), 3),
        "net": round(float(best_w.sum()) * 100, 1),
        "bestPair": round(float(seeds[0][0]), 1) if seeds else None,
        "curve": _series(sc.index, sc.curve(best_w)),
        "equalCurve": _series(sc.index, sc.curve(eq)),
    }


def _fill(target: float, unit: float, small: float, small_name: str,
          code: str, fee_std: float = 0.0, fee_small: float = 0.0) -> dict:
    """Whole contracts closest to `target` dollars, standards and smalls mixed.

    A pure-standard fill on a leg worth 1.4 contracts is 40% off whichever way
    it rounds, and a pure-small fill of the same leg is 140 tickets. The mix is
    what a person would actually send: as many standards as fit, then smalls to
    close the gap. Both are the same underlying, so the combination is one
    position and not a basis trade.
    """
    if not unit or unit <= 0:
        return {"text": "—", "notional": 0.0, "err": None, "fee": 0.0}
    want, sign = abs(target), (1 if target >= 0 else -1)
    # Standards first: {floor, floor+1} of them. Zero is in that set only when
    # the leg is smaller than one contract, which is the case where smalls ARE
    # the position rather than a top-up.
    lots = {max(int(want // unit), 0), max(int(want // unit) + 1, 0)}
    cands = []
    for a in lots:
        rest = want - a * unit
        exact = max(int(round(rest / small)), 0) if small else 0
        # Three ways to finish: stop at whole standards, top up by a handful,
        # or close the gap exactly however many smalls that takes.
        for b in {0, min(exact, TOPUP_SMALLS), exact}:
            got = a * unit + b * small
            cands.append((abs(got - want), a * fee_std + b * fee_small,
                          a + b, a, b, got))
    # Tolerance decides which fills are candidates; COMMISSION decides between
    # them. Among fills landing within 2% of the leg, take the cheapest to
    # send — 22 ETH beats 22 ETH and 5 METs to shave 1.8%, and now for a
    # reason denominated in dollars rather than in tidiness. Only when nothing
    # is within tolerance does precision win, because a hedge 10% away from
    # the one ranked costs more than any ticket.
    # Ticket count sits behind commission in the ordering rather than being
    # replaced by it: with fees switched off the cheapest fill is every
    # fill, and 362 micro tickets came straight back as free precision.
    ok = [c for c in cands if want and c[0] / want * 100 <= HEDGE_TOL]
    err, fee, _n, a, b, got = (
        min(ok, key=lambda c: (round(c[1], 2), c[2], c[0])) if ok
        else min(cands, key=lambda c: (round(c[0], 6), c[1], c[2])))
    if not (a or b):
        # Nothing is a legitimate answer, and on a leg whose smallest ticket
        # is four times its target it is the RIGHT one. The alternative — one
        # contract, 330% of the intended size — is not a rounding error, it is
        # a different position wearing this one's name.
        # -100%, not "no answer": the leg is entirely absent from the fill,
        # which is a miss of the whole thing and belongs in the same column as
        # every other miss rather than hiding behind a dash.
        return {"text": "—", "notional": 0.0, "err": -100.0, "lots": 0,
                "fee": 0.0, "std": 0, "small": 0, "unit": unit}
    parts = []
    if a:
        parts.append(f"{sign * a:+d} {code}")
    if b:
        parts.append(f"{'+' if sign > 0 else '-'}{b} {small_name}"
                     if a else f"{sign * b:+d} {small_name}")
    return {"text": " ".join(parts) if parts else "—",
            "notional": sign * got, "lots": a + b, "fee": round(fee, 2),
            "std": a, "small": b,
            "err": round((got / want - 1) * 100, 1) if want else None}


def plan(closes, fine, res: dict, capital: float, vol_target: float,
         last: dict, mult: dict, micro: dict, max_lev=None,
         fees: dict = None, fee_tier: float = 1.0,
         margins: dict = None) -> dict:
    """Turn a weight vector into money, contracts, and what those score.

    Weights first, contracts second, and the difference measured rather than
    assumed away. Searching integer contract counts directly would tie the
    answer to today's capital and today's prices — change either and the whole
    search is stale — where a weight vector is a shape that survives both. The
    price of doing it in that order is rounding, so the rounding is reported:
    every leg carries how far its fill lands from the target, and the basket is
    rescored AS FILLED beside the ideal.
    """
    if not res or not res.get("weights"):
        return {}
    sc = _Scorer(closes, fine)
    pvol = res["stats"].get("vol") or 0
    # vol_target None means "size on leverage instead": hold the cap and let
    # the volatility land where the basket puts it. The two rules answer
    # different questions — how much risk do I want, versus how much of the
    # account do I want working — and neither is wrong.
    if vol_target is None:
        want = max_lev or 1.0
    else:
        want = (vol_target / pvol) if pvol > 0 else 0
    # A vol target alone will happily ask for six times the account on a quiet
    # basket. The cap is where that gets answered, and when it binds the
    # portfolio simply runs below target — which is worth saying out loud
    # rather than leaving the reader to divide two numbers.
    lev = min(want, max_lev) if max_lev else want
    gross = capital * lev

    legs, achieved = [], np.zeros(len(sc.syms))
    idx = {s: i for i, s in enumerate(sc.syms)}
    for w in res["weights"]:
        code, sym = w["code"], w["sym"]
        target = gross * w["w"] / 100          # signed dollars
        px, m = last.get(code), mult.get(code)
        unit = px * m if (px and m) else None
        mic = micro.get(code)
        small = px * mic[1] if (mic and px) else 0.0
        fee_std, fee_small = (fees or {}).get(code, (0.0, 0.0))
        f = (_fill(target, unit, small, mic[0] if mic else "", code,
                   (fee_std or 0.0) * fee_tier, (fee_small or 0.0) * fee_tier)
             if unit else {"text": "—", "notional": 0.0, "err": None,
                           "fee": 0.0})
        if sym in idx and capital:
            # Fraction of CAPITAL, not of gross: that is the levered weight,
            # so stats() on it reports the position as held.
            achieved[idx[sym]] = f["notional"] / capital
        # What it would take to hold this leg: a fill appears once the leg
        # passes half a contract, so the capital that gets there is that half
        # divided by the leg's own share of gross. More useful than "no" —
        # the answer is usually within reach.
        needs = None
        if unit and not f.get("lots") and w["w"] and lev:
            needs = (unit / 2) / (abs(w["w"]) / 100) / lev
        # Margin on the position that can actually be sent, not on the ideal.
        # A small contract's margin is not published here, but margin tracks
        # notional closely enough that dividing the standard's by the same
        # divisor is right to a few percent — and a few percent of a margin
        # estimate is not what decides whether a basket fits.
        maint = (margins or {}).get(code)
        marg = None
        if maint:
            marg = f.get("std", 0) * maint
            if mic and f.get("small"):
                marg += f["small"] * maint / mic[2]
        legs.append(dict(w, notional=target, unit=unit, fill=f, needs=needs,
                         margin=marg,
                         small=(mic[0] if mic else None),
                         smallUnit=small or None))

    # Every statistic AT THE SIZE HELD. Ratios do not move with leverage but
    # Vol%, Tot% and MDD% do, and reporting the unit-gross basket next to a
    # 0.63x sizing was quietly showing a 31% volatility for a portfolio held
    # at 20% — the one number the vol target exists to set.
    w = np.array(res.get("w") or [])
    eqw = np.array(res.get("equalW") or [])
    sized = sc.stats(w * lev) if w.size else None
    sized_eq = sc.stats(eqw * lev) if eqw.size else None
    filled = None
    if np.abs(achieved).sum() > 0:
        # Rescored on the position that can actually be sent: same shape only
        # if the rounding was kind, which is exactly what needs checking.
        filled = sc.stats(achieved)
        # achieved is a fraction of CAPITAL, so the gross it implies is
        # against capital too. Multiplying by `gross` counted the
        # leverage twice and reported a fill 1.7x its own target.
        filled["gross"] = float(np.abs(achieved).sum()) * capital
    # One round turn, in and out. Against a window's return it is usually
    # noise; against 11,000 micro tickets it was not, which is the whole
    # reason the fill chooser now spends in dollars.
    fee_total = sum((l["fill"].get("fee") or 0.0) for l in legs)
    marg_total = sum((l.get("margin") or 0.0) for l in legs)
    tot = (res["stats"].get("tot") or 0) * lev
    return {"legs": legs, "lev": lev, "wantLev": want, "gross": gross,
            "fees": fee_total,
            "margin": marg_total,
            "marginPct": (marg_total / capital * 100) if capital else 0,
            "feeBps": (fee_total / capital * 10_000) if capital else 0,
            "feeShare": (fee_total / capital * 100 / abs(tot) * 100)
            if capital and tot else None,
            "sized": sized, "sizedEqual": sized_eq, "pvol": pvol,
            "capped": bool(max_lev and want > max_lev + 1e-9),
            "volAt": pvol * lev,
            "target": sum(abs(l["notional"]) for l in legs),
            "filled": filled,
            "undersized": [l["code"] for l in legs
                           if l["fill"]["text"] == "—" or not l["fill"].get("lots")]}


CURVE_PTS = 220


def _series(index, r: np.ndarray) -> dict:
    """Rebased to 100 and thinned, in the shape sk_charts draws."""
    cum = np.empty(len(r) + 1)
    cum[0] = 100.0
    np.cumprod(1 + r, out=cum[1:])
    cum[1:] *= 100.0
    idx = index[:1].append(index) if hasattr(index, "append") else index
    step = max(1, int(np.ceil(len(cum) / CURVE_PTS)))
    keep = list(range(0, len(cum), step))
    if keep[-1] != len(cum) - 1:
        keep.append(len(cum) - 1)
    fmt = "%d %b %H:%M" if (index[-1] - index[0]).days < 20 else "%d %b"
    return {"t": [idx[i].strftime(fmt) for i in keep],
            "v": [round(float(cum[i]), 2) for i in keep]}
