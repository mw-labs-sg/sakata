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
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import numpy as np
import pandas as pd

import sk_universe as U

DRY = False          # set by build.py --dry; swaps prices for synthetic series

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
    n, freq = ((1400, "h") if interval == "1h" else
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


def fetch_ohlc(interval: str, period: str) -> dict:
    """{code: DataFrame[open,high,low,close]} — one Yahoo call per instrument."""
    if DRY:
        return _synth(interval)
    import yfinance as yf
    out = {}
    for code in U.CODES:
        try:
            h = yf.Ticker(U.TICKER[code], session=session()).history(
                period=period, interval=interval, auto_adjust=True)
            if h is None or h.empty:
                print(f"    {interval} {code}: empty")
                continue
            h.columns = [str(c).lower() for c in h.columns]
            if not {"open", "high", "low", "close"}.issubset(h.columns):
                continue
            h = h[["open", "high", "low", "close"]].dropna()
            if getattr(h.index, "tz", None) is not None:
                h.index = h.index.tz_localize(None)
            if interval == "1d":
                h.index = h.index.normalize()
            out[code] = h[~h.index.duplicated(keep="last")]
        except Exception as e:
            print(f"    {interval} {code} failed: {str(e)[:70]}")
    return out


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return (df.resample("4h", label="left", closed="left")
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


def fetch_margins() -> dict:
    """{code: {maint, day}} scraped by matching cell VALUES, not headers."""
    if DRY:
        return {c: {"maint": 1000 + 500 * (i % 7), "day": 500 + 250 * (i % 5)}
                for i, c in enumerate(U.CODES)}
    want = {c for c in U.CODES}
    out = {}
    try:
        html = session().get(AMP_URL, timeout=25).text
    except Exception as e:
        print(f"    AMP failed: {str(e)[:60]}")
        return out
    for t in pd.read_html(io.StringIO(html)):
        for row in t.itertuples(index=False):
            cells = [str(c).strip() for c in row if str(c).strip().lower() != "nan"]
            sym = next((c for c in cells if c in want), None)
            if not sym or sym in out:
                continue
            monies = [m for m in (num(c) for c in cells
                                  if str(c).strip().startswith("$")) if m is not None]
            if not monies:
                continue
            out[sym] = {"maint": monies[0],
                        "day": monies[1] if len(monies) > 1 else None}
    # BTC/ETH are not on AMP's list — CME's outright CSV carries them.
    for code in ("BTC", "ETH"):
        if code in out:
            continue
        try:
            csv = session().get(
                "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv",
                timeout=25).text
            df = pd.read_csv(io.StringIO(csv))
            hit = df[df["Product Code"].astype(str).str.strip().str.upper() == code]
            if not hit.empty:
                out[code] = {"maint": num(hit.iloc[0]["Maintenance"]), "day": None}
        except Exception:
            pass
    return out


# ------------------------------------------------------------------- news
def fetch_te(url: str) -> dict:
    """Lead commentary blurb from a Trading Economics market page."""
    try:
        html = session().get(url, timeout=25).text
        from bs4 import BeautifulSoup
    except Exception as e:
        return {"blurb": "", "err": str(e)[:60]}
    soup = BeautifulSoup(html, "html.parser")
    anchor = None
    for a in soup.select("a[href*='/news/']"):
        if re.search(r"/news/\d+", a.get("href", "")) and a.get_text(strip=True):
            anchor = a
            break
    if anchor is None:
        return {"blurb": ""}
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
    return {"headline": headline, "blurb": blurb, "date": date}


def _strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(s)).strip()


def fetch_rss(url: str, n: int = 14) -> list:
    try:
        xml = session().get(url, timeout=25).text
        root = ET.fromstring(xml)
    except Exception:
        return []
    nodes = root.findall(".//item")
    atom = False
    if not nodes:
        nodes = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        atom = True
    a = "{http://www.w3.org/2005/Atom}"

    def txt(node, *tags):
        for t in tags:
            el = node.find(t)
            if el is not None:
                if el.text:
                    return el.text
                if el.get("href"):
                    return el.get("href")
        return ""

    out = []
    for it in nodes[:n]:
        if atom:
            title, link = txt(it, f"{a}title"), txt(it, f"{a}link")
            raw, summ = txt(it, f"{a}updated", f"{a}published"), txt(it, f"{a}summary")
        else:
            title, link = txt(it, "title"), txt(it, "link")
            raw, summ = txt(it, "pubDate"), txt(it, "description")
        when = ""
        if raw:
            try:
                when = parsedate_to_datetime(raw).strftime("%Y-%m-%d %H:%M")
            except Exception:
                when = raw[:16]
        summ = _strip_html(summ)
        if len(summ) > 240:
            summ = summ[:240].rsplit(" ", 1)[0] + "\u2026"
        title = _strip_html(title)
        if title:
            out.append({"title": title, "link": link.strip(),
                        "when": when, "summary": summ})
    return out


def fetch_news() -> dict:
    if DRY:
        return {"markets": {c: {"blurb": f"Synthetic commentary for {c}.",
                                "date": str(dt.date.today())}
                            for c in list(U.TE_PAGE)[:6]},
                "wire": [{"title": "Synthetic headline", "link": "#",
                          "when": "2026-01-01 00:00", "summary": "dry run"}]}
    markets = {}
    for code, url in U.TE_PAGE.items():
        d = fetch_te(url)
        if d.get("blurb"):
            markets[code] = {"blurb": d["blurb"], "date": d.get("date", "")}
        else:
            print(f"    TE {code}: nothing parsed")
    wire = []
    for name, url in U.RSS_FEEDS.items():
        wire += fetch_rss(url)
    return {"markets": markets, "wire": wire}
