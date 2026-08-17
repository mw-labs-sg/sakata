"""build.py — the whole site, built on a GitHub runner.

    python build.py           # live fetch, writes docs/
    python build.py --dry     # synthetic prices, no network (for testing)

Fetches three price passes (hourly, daily, weekly), computes every tab, and
writes docs/data/*.json plus the static shell. Nothing is fetched in the
browser: the page is a viewer over committed JSON.
"""
import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

# The project floor, declared in pyproject.toml and enforced here. This path
# does not import sk_render, but the floor is the whole repo's, and failing with
# a sentence beats failing four modules deep.
if sys.version_info < (3, 12):
    raise SystemExit(
        "Sakata needs Python 3.12+ (sk_render.py uses PEP 701 f-strings); "
        f"this interpreter is {sys.version.split()[0]}.")

import sk_board as BOARD
import sk_curve as CURVE
import sk_knowledge as KN
import sk_margins as MARGIN
import sk_sources as S
import sk_spreads as SP
import sk_technical as TECH
import sk_universe as U

ROOT = Path(__file__).parent
OUT = ROOT / "docs"
DATA = OUT / "data"
SITE = ROOT / "site"


def write(name: str, obj) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / name
    p.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {p.relative_to(ROOT)} ({p.stat().st_size / 1024:,.0f} KB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="synthetic prices, no network")
    ap.add_argument("--skip", default="", help="comma list: curve,margins")
    args = ap.parse_args()
    S.DRY = args.dry
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    now = dt.datetime.now(dt.timezone.utc)

    # ---------------------------------------------------------- prices
    # Two network passes, not three. 4h and weekly are aggregations of bars
    # already in hand, so fetching them separately buys nothing and costs a
    # round trip that can fail on its own.
    print("prices: 15-minute 60d")
    m15 = S.fetch_ohlc("15m", "60d")
    print("prices: hourly 730d")
    hourly = S.fetch_ohlc("1h", "730d")
    print("prices: daily 10y")
    daily = S.fetch_ohlc("1d", "10y")
    if len(daily) < 2 and len(hourly) < 2:
        print("no price data at all — aborting so the last good build survives")
        return 1
    four_h = {k: S.resample_4h(v) for k, v in hourly.items()}
    weekly = {k: S.resample_weekly(v) for k, v in daily.items()}
    by_bar = {"1h": hourly, "4h": four_h, "1d": daily, "1wk": weekly}

    # ---------------------------------------------------------- compute
    print("board")
    write("board.json", BOARD.build_board(daily))

    print("technical")
    write("technical.json", TECH.build_technical(by_bar))

    print("spreads")
    # Closes only, keyed by ticker — every window slices from these, so the
    # nine of them cost no extra network at all.
    def closes(frames):
        return {U.TICKER[c]: df["close"].dropna()
                for c, df in frames.items() if df is not None and len(df)}
    write("spreads.json", SP.build_spreads({
        "15m": closes(m15), "1h": closes(hourly),
        "4h": closes(four_h), "1d": closes(daily)}))

    if "margins" not in skip:
        print("margins")
        write("margins.json", MARGIN.build_margins(S.fetch_margins(), daily))

    if "curve" not in skip:
        print("curve")
        write("curve.json", CURVE.build_curve(S.fetch_curves()))

    # ------------------------------------------------------------ meta
    write("meta.json", {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "instruments": len(U.CODES),
        "universe": [{"code": c, "name": U.NAME[c], "sector": U.SECTOR[c],
                      "group": U.GROUP_OF[U.SECTOR[c]], "dec": U.DEC[c]}
                     for c in U.CODES],
        "groups": U.GROUPS,
        "knowledge": {c: [{"t": t, "d": d} for t, d in KN.KNOWLEDGE.get(c, [])]
                      for c in U.CODES},
        # News is fetched IN THE BROWSER now, so the page needs the page list.
        "te": U.TE_PAGE,
        "dry": bool(args.dry),
    })

    # ------------------------------------------------------------ shell
    OUT.mkdir(exist_ok=True)
    # Copy the tree, not a hardcoded list. The shell is one file per tab now,
    # so a named list would silently drop any file added later — exactly the
    # failure that looks like "my change did not deploy".
    for src in sorted(SITE.rglob("*")):
        if src.is_dir():
            continue
        dst = OUT / src.relative_to(SITE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        print(f"  copied {dst.relative_to(OUT)}")
    (OUT / ".nojekyll").write_text("")
    print(f"\ndone — open {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
