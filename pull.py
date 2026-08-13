"""pull.py — refresh ONE dataset now, without a full build or an Action.

    python pull.py news
    python pull.py margins
    python pull.py curve
    python pull.py news margins

Writes straight into docs/data/, leaving every other file untouched, so a
broken scraper can never take out prices you already have. This is the same
idea as SANPO's fetch_news.py: the slow, fragile, occasionally-wrong sources
should be refreshable by hand, on demand, without waiting for a schedule.

Prices are deliberately NOT here. They are three batched calls and the whole
point of `python build.py`; refreshing them alone would leave the computed
tabs disagreeing with the board.
"""
import json
import sys
from pathlib import Path

import sk_sources as S
import sk_tabs as T

DATA = Path(__file__).parent / "docs" / "data"

JOBS = {
    "news":    lambda: S.fetch_news(),
    "margins": lambda: T.build_margins(S.fetch_margins(), _daily()),
    "curve":   lambda: T.build_curve(S.fetch_curves()),
}
_cache = {}


def _daily():
    """Margins needs last price and ATR, so it needs the daily bars. Fetched
    once and reused if several jobs ask for them."""
    if "daily" not in _cache:
        print("  prices: daily 10y (margins needs notional and ATR)")
        _cache["daily"] = S.fetch_ohlc("1d", "10y")
    return _cache["daily"]


def main(argv):
    jobs = [a for a in argv if a in JOBS]
    if not jobs:
        print(f"usage: python pull.py [{' | '.join(JOBS)}] ...")
        return 2
    if not DATA.exists():
        print(f"no {DATA} — run a full build first")
        return 1
    for name in jobs:
        print(f"{name}:")
        try:
            obj = JOBS[name]()
        except Exception as e:
            print(f"  FAILED — {str(e)[:90]}\n  left the existing file alone")
            continue
        # An empty result is a failed scrape wearing a success costume. Never
        # overwrite good data with it.
        if not obj or (isinstance(obj, dict) and not any(obj.values())):
            print("  came back empty — keeping the existing file")
            continue
        p = DATA / f"{name}.json"
        p.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
        print(f"  wrote {p} ({p.stat().st_size / 1024:,.0f} KB)")
    print("\ncommit docs/data/*.json to publish")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
