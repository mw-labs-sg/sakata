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

    def score(self, w: np.ndarray, objective: str) -> float:
        """One number, higher better. -inf for anything unrankable.

        Scored on the same definitions the stats report, with one extra
        condition on ROA. Ranking a table of pairs, a suspiciously small
        drawdown is a curiosity; SEARCHING for the largest ratio makes it the
        objective, and a hill climb will happily spend its whole budget
        shrinking the denominator. So a portfolio whose worst hole is smaller
        than one typical bar of its own movement is not scored: it did not
        avoid a drawdown, it was measured too coarsely to have had one.
        """
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


def optimise(closes: pd.DataFrame, fine=None, objective: str = "ROA",
             max_legs: int = 4, max_weight: float = 0.5,
             allow_short: bool = True, tries: int = 1500,
             climbs: int = 250, seed: int = 0) -> dict:
    """Search weights maximising `objective` over the window in `closes`.

    Random restarts to find the neighbourhood, then a shrinking-step climb
    inside it. The seed is fixed: an optimiser that answers differently every
    rerun teaches nobody anything, and the run-to-run spread is a property of
    the search rather than of the market.
    """
    if closes is None or closes.shape[1] < 2 or len(closes) < 10:
        return {}
    sc = _Scorer(closes, fine)
    n = len(sc.syms)
    max_legs = max(2, min(max_legs, n))
    rng = np.random.default_rng(seed)

    best_w, best_v = None, -np.inf
    for _ in range(tries):
        k = int(rng.integers(2, max_legs + 1))
        legs = rng.choice(n, size=k, replace=False)
        w = np.zeros(n)
        mag = rng.dirichlet(np.ones(k))
        w[legs] = mag * (rng.choice([-1.0, 1.0], size=k) if allow_short else 1.0)
        w = _project(w, max_legs, max_weight, allow_short)
        v = sc.score(w, objective)
        if v > best_v:
            best_w, best_v = w, v

    if best_w is None:
        return {}

    # Local climb. Perturbing only the legs already held would fix the basket
    # at whatever the random pass happened to like, so every step also gets a
    # chance to swap one leg for an unheld instrument.
    step = 0.25
    for i in range(climbs):
        cand = best_w.copy()
        if rng.random() < 0.25:
            held = np.flatnonzero(cand)
            idle = np.flatnonzero(cand == 0)
            if len(held) and len(idle):
                out_, in_ = rng.choice(held), rng.choice(idle)
                cand[in_], cand[out_] = cand[out_], 0.0
        else:
            cand += rng.normal(0, step, n) * (np.abs(cand) > 0)
        cand = _project(cand, max_legs, max_weight, allow_short)
        v = sc.score(cand, objective)
        if v > best_v:
            best_w, best_v = cand, v
        if i % 50 == 49:
            step *= 0.6

    order = np.argsort(-np.abs(best_w))
    weights = [{"sym": sc.syms[i], "code": ss.name_of(sc.syms[i]),
                "w": round(float(best_w[i]) * 100, 1)}
               for i in order if abs(best_w[i]) > 5e-4]

    # Equal weight over the same legs, as the thing the search has to beat. A
    # portfolio that cannot beat naive weighting on its own objective has found
    # nothing but a way to spend a click.
    eq = np.zeros(n)
    eq[np.flatnonzero(best_w)] = np.sign(best_w[np.flatnonzero(best_w)])
    eq = _project(eq, max_legs, 1.0, allow_short)

    return {
        "objective": objective, "weights": weights,
        "stats": sc.stats(best_w), "equal": sc.stats(eq),
        "bars": sc.bars, "fineBars": sc.fine_bars,
        "legs": len(weights), "gross": round(float(np.abs(best_w).sum()), 3),
        "net": round(float(best_w.sum()) * 100, 1),
        "curve": _series(sc.index, sc.curve(best_w)),
        "equalCurve": _series(sc.index, sc.curve(eq)),
    }


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
