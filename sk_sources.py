"""Sakata — every network call lives here.

All of it runs on a GitHub runner, never in a browser. That is the whole point
of the rebuild: Yahoo, CME and Trading Economics all serve residential and
runner IPs while rate-limiting hosted-app ranges, so fetching at build time and
publishing the result sidesteps the blocking that made the hosted Streamlit app
come back empty.

Every fetcher returns plain data and swallows its own errors — one dead source
must never take the build down with it.
"""
import datetime as dt
import io
import json
import pathlib
import pickle
import re
import time

import numpy as np
import pandas as pd

import sk_universe as U

DRY = False          # set by build.py --dry; swaps prices for synthetic series

# ------------------------------------------------------------- snapshots
# Yahoo rate-limits by IP, and st.cache_data lives in the process, so every
# restart of the app used to re-ask for all three price pulls. Fifteen
# restarts in an hour is forty-five batch downloads from one address, and
# once that trips the limiter the old fallback path made it worse rather
# than better: a batch returning nothing sent nineteen single-ticker
# requests after it, per interval. One throttled call became sixty.
#
# So a good pull is written to disk and a restart reads it back. The three
# fetches are unchanged — this is not about how much is asked for, it is
# about asking again for something already answered.
CACHE_DIR = pathlib.Path(__file__).parent / "data" / "cache"
SNAP_MAX_AGE = 900       # seconds a snapshot serves before the network is asked
SINGLE_CAP = 6           # most instruments ever refetched one at a time


def _snap_path(interval: str, period: str) -> pathlib.Path:
    return CACHE_DIR / f"ohlc-{interval}-{period}.pkl"


def _snap_read(interval: str, period: str):
    """(frames, age in seconds), or (None, None) if there is nothing usable."""
    p = _snap_path(interval, period)
    try:
        with p.open("rb") as fh:
            blob = pickle.load(fh)
        return blob["frames"], time.time() - blob["at"]
    except Exception:        # missing, truncated, or written by another pandas
        return None, None


def _snap_write(interval: str, period: str, frames: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _snap_path(interval, period).with_suffix(".tmp")
        with tmp.open("wb") as fh:
            pickle.dump({"at": time.time(), "frames": frames}, fh,
                        protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(_snap_path(interval, period))
    except Exception as e:   # a cache that cannot be written is not an error
        print(f"    snapshot {interval} not written: {str(e)[:60]}")


def drop_snapshots() -> int:
    """Refresh means refetch. Without this the button would keep serving the
    very snapshot the reader pressed it to get past."""
    n = 0
    try:
        for p in CACHE_DIR.glob("ohlc-*.pkl"):
            p.unlink()
            n += 1
    except Exception:
        pass
    return n

_SESSION = None


def session():
    global _SESSION
    if _SESSION is None:
        from curl_cffi import requests as cffi
        _SESSION = cffi.Session(impersonate="chrome110")
    return _SESSION


def num(x):
    try:
        return float(str(x).replace(",", "").replace("+", "")
                     .replace("$", "").strip())
    except Exception:
        return None


# ------------------------------------------------------------------ prices
def _synth(interval, n=None):
    """Deterministic fake OHLC so --dry exercises the whole path offline."""
    n, freq = ((1500, "15min") if interval == "15m" else
               (1400, "h") if interval == "1h" else
               (3000, "h") if interval == "1h_long" else
               (2500, "B") if interval == "1d" else
               (900, "W-MON") if interval == "1wk" else (1400, "h"))
    idx = pd.date_range(end=dt.datetime.now(), periods=n, freq=freq)
    n = len(idx)          # calendar freqs can return one fewer than requested
    rng = np.random.default_rng(7)
    out = {}
    for i, code in enumerate(U.CODES):
        vol = 0.002 + 0.001 * (i % 5)
        drift = 0.00004 * ((i % 7) - 3)
        close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
        wig = np.abs(rng.normal(0, vol, n)) * close
        out[code] = pd.DataFrame({
            "open": np.r_[close[0], close[:-1]], "high": close + wig,
            "low": close - wig, "close": close}, index=idx)
    return out


def _tidy(h, interval):
    """One frame, normalised: lowercase OHLC, naive index, no duplicate bars."""
    if h is None or len(h) == 0:
        return None
    h = h.copy()
    h.columns = [str(c).lower() for c in h.columns]
    if not {"open", "high", "low", "close"}.issubset(h.columns):
        return None
    h = h[["open", "high", "low", "close"]].dropna()
    if h.empty:
        return None
    if getattr(h.index, "tz", None) is not None:
        h.index = h.index.tz_localize(None)
    if interval == "1d":
        h.index = h.index.normalize()
    return h[~h.index.duplicated(keep="last")]


def fetch_ohlc(interval: str, period: str, max_age: float = None) -> dict:
    """{code: DataFrame[open,high,low,close]} for the whole universe.

    Disk first, network second, and the last good pull rather than nothing
    when the network says no. Serving a fifteen-minute-old snapshot to a
    reader who has just restarted is right on both counts: it is what they
    were looking at a moment ago, and not asking is the only thing that ever
    gets an address back off a rate limiter.
    """
    if DRY:
        return _synth(interval)
    max_age = SNAP_MAX_AGE if max_age is None else max_age
    snap, age = _snap_read(interval, period)
    if snap and age is not None and age < max_age:
        print(f"    {interval}: snapshot {int(age)}s old, not fetching")
        return snap

    fresh = _download_ohlc(interval, period)
    if fresh:
        _snap_write(interval, period, fresh)
        return fresh
    if snap:
        # Stale beats empty. An empty dict renders every tab as an error and
        # loses the reader the session they already had.
        print(f"    {interval}: nothing came back, serving snapshot "
              f"{int(age or 0)}s old")
        return snap
    return {}


def _download_ohlc(interval: str, period: str) -> dict:
    """ONE batched request, not one per instrument. yfinance will take the
    full ticker list and return a column-multiindexed frame, which is a
    single HTTP round trip instead of nineteen.

    The per-ticker path is a patch for a batch that came back SHORT, never
    for one that came back empty. Empty means the address is being refused,
    and nineteen more requests is the worst available response to that — it
    was how one throttled call turned into sixty and kept the limiter fed.
    """
    import yfinance as yf

    tickers = [U.TICKER[c] for c in U.CODES]
    raw, out = None, {}
    # threads=False deliberately. yfinance 1.0's threaded path returns an
    # empty frame for every ticker and prints "N Failed downloads" with a
    # TypeError about NoneType — measured side by side, the same call for the
    # same tickers over the same period gives 0 rows threaded and 2514
    # single-threaded. It reads exactly like an IP block and is not one: the
    # chart endpoint answers 200 with real data from this address throughout.
    #
    # The cost is wall time on one batched request, which is a batched
    # request either way. The alternative was chasing a rate limit that was
    # never there.
    kw = dict(period=period, interval=interval, group_by="ticker",
              auto_adjust=True, threads=False, progress=False)
    for attempt in (dict(kw, session=session()), kw):
        try:
            raw = yf.download(tickers, **attempt)
            break
        except TypeError:
            continue            # older/newer yfinance disagree about session=
        except Exception as e:
            print(f"    {interval} batch failed: {str(e)[:70]}")
            break

    if raw is not None and len(raw):
        multi = isinstance(raw.columns, pd.MultiIndex)
        for code in U.CODES:
            tk = U.TICKER[code]
            try:
                h = raw[tk] if multi else raw
            except KeyError:
                continue
            t = _tidy(h, interval)
            if t is not None:
                out[code] = t

    missing = [c for c in U.CODES if c not in out]
    if not out:
        print(f"    {interval}: batch returned nothing, not refetching "
              f"{len(missing)} singly")
        return {}
    if len(missing) > SINGLE_CAP:
        print(f"    {interval}: {len(missing)} missing, over the cap, "
              f"taking what the batch gave")
        return out
    for code in missing:
        try:
            h = yf.Ticker(U.TICKER[code], session=session()).history(
                period=period, interval=interval, auto_adjust=True)
            t = _tidy(h, interval)
            if t is None:
                print(f"    {interval} {code}: empty")
                continue
            out[code] = t
        except Exception as e:
            print(f"    {interval} {code} failed: {str(e)[:70]}")
    if missing:
        print(f"    {interval}: {len(missing)} refetched singly "
              f"({', '.join(missing[:6])})")
    return out


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return (df.resample("4h", label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last"}).dropna())


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly bars from daily. There is no reason to ask Yahoo for these —
    a weekly bar IS the daily bars aggregated, and ten years of daily gives
    ~520 weekly bars, comfortably past the 200 the Year rung needs."""
    return (df.resample("W-MON", label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last"}).dropna())


# -------------------------------------------------------------------- CME
CME_URL = ("https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/"
           "Settlements/{pid}/FUT?tradeDate={td}")
CME_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ("https://www.cmegroup.com/markets/energy/crude-oil/"
                "light-sweet-crude.settlements.html"),
    "X-Requested-With": "XMLHttpRequest",
}


def _business_days(n=6):
    days, d = [], dt.date.today()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return days


def resolve_tradedate():
    """One probe on CL to find a date string the endpoint accepts."""
    for day in _business_days():
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
            td = day.strftime(fmt)
            try:
                r = session().get(CME_URL.format(pid=425, td=td),
                                  headers=CME_HEADERS, timeout=25)
                if r.json().get("settlements"):
                    return td
            except Exception:
                continue
    return None


def _settlement_rows(settlements):
    out = []
    for s in settlements or []:
        month = str(s.get("month", "")).strip()
        if not month or month.lower() in ("total", "totals"):
            continue
        price = next((p for p in (num(s.get("settle")), num(s.get("last")),
                                  num(s.get("priorSettle"))) if p is not None), None)
        if price is None:
            continue
        out.append({"month": month, "settle": price,
                    "chg": str(s.get("change", "")).strip(),
                    "vol": str(s.get("volume", "")).strip(),
                    "oi": str(s.get("openInterest", "")).strip()})
    return out


def fetch_curves() -> dict:
    """{code: [rows]} of settlement curves, plus the trade date used."""
    if DRY:
        base = {"CL": 82, "GC": 3400, "ES": 6900, "NG": 3.4, "ZC": 450}
        out = {}
        for code, pid in list(U.CME_PRODUCT.items()):
            p0 = base.get(code, 100.0)
            rows = []
            for i in range(14):
                d = dt.date.today().replace(day=1) + dt.timedelta(days=31 * (i + 1))
                slope = -0.004 if code in ("CL", "NG") else 0.003
                rows.append({"month": d.strftime("%b %y").upper(),
                             "settle": round(p0 * (1 + slope * i), 3),
                             "chg": "+0.1", "vol": "1200", "oi": str(9000 - 400 * i)})
            out[code] = rows
        return {"tradeDate": "DRY", "curves": out}

    td = resolve_tradedate()
    print(f"  CME tradeDate: {td}")
    curves = {}
    if td:
        for code, pid in U.CME_PRODUCT.items():
            try:
                data = session().get(CME_URL.format(pid=pid, td=td),
                                     headers=CME_HEADERS, timeout=25).json()
                rows = _settlement_rows(data.get("settlements"))
            except Exception as e:
                print(f"    CME {code} failed: {str(e)[:60]}")
                rows = []
            if rows:
                curves[code] = rows
    return {"tradeDate": td, "curves": curves}


# -------------------------------------------------------------------- AMP
AMP_URL = "https://www.ampfutures.com/trading-info/margins"


# ------------------------------------------------------------------- news
# What a story about THIS instrument would mention. Used to choose among the
# news anchors on a market page rather than taking whichever one the page leads
# with — the US stock-market page led with a Dow story, so the ES card carried
# several paragraphs about the Dow under an "ES  S&P 500" heading.
TE_SUBJECT = {
    "ES": ("s&p", "sp500", "s&p 500"),
    "NKD": ("nikkei", "japan"),
    "ZB": ("treasury", "bond", "yield"),
    "6E": ("euro", "eur"),
    "6J": ("yen", "jpy", "japanese"),
    "CL": ("crude", "oil", "wti", "brent"),
    "NG": ("natural gas", "gas"),
    "GC": ("gold", "bullion"),
    "SI": ("silver",),
    "HG": ("copper",),
    "ZC": ("corn",),
    "ZW": ("wheat",),
    "ZS": ("soybean", "soy"),
    "SB": ("sugar",),
    "KC": ("coffee", "arabica"),
}


def fetch_te(url: str, code: str = "") -> dict:
    """Lead commentary blurb from a Trading Economics market page.

    Prefers a story whose headline actually names the instrument. The old rule
    took the first /news/ anchor on the page, which is whatever TE is leading
    with — measured live, that put a Dow Jones write-up under ES. Falls back to
    the first anchor when nothing matches, and reports which happened via
    `onTopic` so a mismatch is visible rather than silent.
    """
    try:
        html = session().get(url, timeout=25).text
        from bs4 import BeautifulSoup
    except Exception as e:
        return {"blurb": "", "err": f"{type(e).__name__}: {str(e)[:50]}"}
    soup = BeautifulSoup(html, "html.parser")
    cands = [a for a in soup.select("a[href*='/news/']")
             if re.search(r"/news/\d+", a.get("href", ""))
             and a.get_text(strip=True)]
    if not cands:
        return {"blurb": "", "err": "no news anchors on the page"}
    words = TE_SUBJECT.get(code, ())
    anchor, on_topic = cands[0], not words
    for a in cands:
        if any(w in a.get_text(strip=True).lower() for w in words):
            anchor, on_topic = a, True
            break
    headline = anchor.get_text(strip=True)
    blurb, date, node = "", "", anchor
    for _ in range(5):
        node = node.find_parent()
        if node is None:
            break
        txt = node.get_text(" ", strip=True)
        i = txt.find(headline)
        after = txt[i + len(headline):] if i >= 0 else txt
        m = re.search(r"(20\d\d-\d\d-\d\d)", after)
        if m and m.start() > 40:
            blurb, date = after[:m.start()].strip(), m.group(1)
            break
    return {"headline": headline, "blurb": blurb, "date": date,
            "onTopic": on_topic}
