"""Sakata — JSON number formatting, shared by every tab module.

Two rules, both learned the hard way. NaN and inf must become null, not the
strings "nan" and "Infinity", or the page renders the word instead of a gap.
And series arrays round to SIGNIFICANT figures rather than fixed decimals:
fixed decimals ship useless precision on BTC and useful precision on 6J, while
significant figures get both right and halve the payload.
"""
import numpy as np


def r(v, n=4):
    """Round for JSON, mapping NaN/inf to None so JS gets null not a string."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, n)


def sig(v, digits=7):
    """Significant-figure rounding for the compact series arrays."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return float(f"{f:.{digits}g}")
