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

import sk_sources as S
import sk_spreads as SP
import sk_tabs as T
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
    ap.add_argument("--skip", default="", help="comma list: news,curve,margins")
    args = ap.parse_args()
    S.DRY = args.dry
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    now = dt.datetime.now(dt.timezone.utc)

    # ---------------------------------------------------------- prices
    print("prices: hourly 730d")
    hourly = S.fetch_ohlc("1h", "730d")
    print("prices: daily 10y")
    daily = S.fetch_ohlc("1d", "10y")
    print("prices: weekly max")
    weekly = S.fetch_ohlc("1wk", "max")
    if len(daily) < 2 and len(hourly) < 2:
        print("no price data at all — aborting so the last good build survives")
        return 1
    four_h = {k: S.resample_4h(v) for k, v in hourly.items()}
    by_bar = {"1h": hourly, "4h": four_h, "1d": daily, "1wk": weekly}

    # ---------------------------------------------------------- compute
    print("board")
    write("board.json", T.build_board(daily))

    print("technical")
    write("technical.json", T.build_technical(by_bar))

    print("spreads")
    write("spreads.json", SP.build_spreads(daily, hourly))

    if "margins" not in skip:
        print("margins")
        write("margins.json", T.build_margins(S.fetch_margins(), daily))

    if "curve" not in skip:
        print("curve")
        write("curve.json", T.build_curve(S.fetch_curves()))

    if "news" not in skip:
        print("news")
        write("news.json", S.fetch_news())

    # ------------------------------------------------------------ meta
    write("meta.json", {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "instruments": len(U.CODES),
        "universe": [{"code": c, "name": U.NAME[c], "sector": U.SECTOR[c],
                      "group": U.GROUP_OF[U.SECTOR[c]], "dec": U.DEC[c]}
                     for c in U.CODES],
        "groups": U.GROUPS,
        "dry": bool(args.dry),
    })

    # ------------------------------------------------------------ shell
    OUT.mkdir(exist_ok=True)
    for f in ("index.html", "sakata.css", "sakata.js"):
        shutil.copy(SITE / f, OUT / f)
        print(f"  copied {f}")
    (OUT / ".nojekyll").write_text("")
    print(f"\ndone — open {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
