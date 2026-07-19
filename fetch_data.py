"""
fetch_data.py — runs in GitHub Actions (not in the app).

Fetches from GitHub's runner IPs (which the exchanges don't block the way they
block cloud-app IPs), then writes clean JSON into data/ for Sakata to read.

Outputs:
  data/curves.json   {generated, tradeDate, curves: {name: [rows...]}}
  data/margins.json  {generated, date, rows: [{...}]}   (one file per run; the
                     commit history itself is the day/week archive)
"""

import datetime as dt
import io
import json
from pathlib import Path

import pandas as pd
from curl_cffi import requests as cffi_requests

session = cffi_requests.Session(impersonate="chrome110")
OUT = Path("data")
OUT.mkdir(exist_ok=True)

# --- CME (confirmed productIds; add NQ/6E/6J/ZB/ZN/BTC/ETH once known) --------
CME_PRODUCTS = {
    "ES  S&P 500": 133, "CL  Crude": 425, "NG  Nat Gas": 444,
    "GC  Gold": 437, "SI  Silver": 458, "HG  Copper": 438,
    "ZC  Corn": 300, "ZW  Wheat": 323, "ZS  Soybean": 320,
}
CME_URL = ("https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/"
           "Settlements/{pid}/FUT?tradeDate={td}")
CME_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ("https://www.cmegroup.com/markets/energy/crude-oil/"
                "light-sweet-crude.settlements.html"),
    "X-Requested-With": "XMLHttpRequest",
}

AMP_URL = "https://www.ampfutures.com/trading-info/margins"
AMP_SYMBOLS = ["ES", "NQ", "ZB", "ZN", "6E", "6J", "CL", "NG", "GC", "SI",
               "HG", "ZC", "ZW", "ZS", "SB", "KC"]


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("+", "").replace("$", "").strip())
    except Exception:
        return None


def _business_days(n=6):
    days, d = [], dt.date.today()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return days


def resolve_tradedate():
    for day in _business_days():
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
            td = day.strftime(fmt)
            try:
                r = session.get(CME_URL.format(pid=425, td=td),
                                headers=CME_HEADERS, timeout=25)
                data = r.json()
                if data.get("settlements"):
                    return td
            except Exception:
                continue
    return None


def _rows_from_settlements(settlements):
    out = []
    for s in settlements or []:
        month = str(s.get("month", "")).strip()
        if not month or month.lower() in ("total", "totals"):
            continue
        price = next((p for p in (_num(s.get("settle")), _num(s.get("last")),
                                  _num(s.get("priorSettle"))) if p is not None), None)
        if price is None:
            continue
        out.append({"Month": month, "Settle": price, "Change": s.get("change", ""),
                    "Volume": s.get("volume", ""), "OI": s.get("openInterest", "")})
    return out


def fetch_cme(pid, td):
    try:
        data = session.get(CME_URL.format(pid=pid, td=td),
                           headers=CME_HEADERS, timeout=25).json()
        return _rows_from_settlements(data.get("settlements"))
    except Exception as e:
        print(f"  CME {pid} failed: {e}")
        return []


def _norm_ice_month(s):
    import re
    m = re.match(r"\s*([A-Za-z]{3})[A-Za-z]*\s*'?(\d{2,4})", str(s))
    return f"{m.group(1).upper()} {m.group(2)[-2:]}" if m else ""


# --- Barchart softs (SB, KC) via the free core-api + token handshake ----------
BARCHART_SOFTS = {"SB  Sugar": "SB", "KC  Coffee": "KC"}
_BC_MONTH = {"F": "JAN", "G": "FEB", "H": "MAR", "J": "APR", "K": "MAY",
             "M": "JUN", "N": "JUL", "Q": "AUG", "U": "SEP", "V": "OCT",
             "X": "NOV", "Z": "DEC"}


def fetch_barchart(root):
    import urllib.parse
    try:
        # 1) hit the page to receive the XSRF-TOKEN cookie
        session.get(f"https://www.barchart.com/futures/quotes/{root}*0",
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        token = session.cookies.get("XSRF-TOKEN")
        token = urllib.parse.unquote(token) if token else ""
        # 2) call the core-api for all contracts of the root
        url = ("https://www.barchart.com/proxies/core-api/v1/quotes/get"
               f"?symbols={root}%5EF&fields=symbol,lastPrice,openInterest,volume&raw=1")
        r = session.get(url, timeout=25, headers={
            "X-XSRF-TOKEN": token,
            "Referer": f"https://www.barchart.com/futures/quotes/{root}*0",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        })
        print(f"  Barchart {root}: HTTP {r.status_code}, first 300 chars:")
        print("  " + repr(r.text[:300]))
        data = r.json().get("data", [])
    except Exception as e:
        print(f"  Barchart {root} failed: {e}")
        return []
    rows = []
    for c in data:
        sym = str(c.get("symbol", ""))
        raw = c.get("raw", c) or c
        if len(sym) < 3 or not sym.startswith(root):
            continue
        code = sym[len(root):-2][-1:]          # month letter
        yr = sym[-2:]
        mon = _BC_MONTH.get(code)
        settle = _num(raw.get("lastPrice"))
        if not mon or settle is None:
            continue
        rows.append({"Month": f"{mon} {yr}", "Settle": settle, "Change": "",
                     "Volume": raw.get("volume", ""), "OI": raw.get("openInterest", "")})
    return rows


def fetch_margins():
    try:
        html = session.get(AMP_URL, timeout=25).text
    except Exception as e:
        print(f"  AMP failed: {e}")
        return []
    want = set(AMP_SYMBOLS)
    rows, seen = [], set()
    for t in pd.read_html(io.StringIO(html)):
        for row in t.itertuples(index=False):
            cells = [str(c).strip() for c in row if str(c).strip().lower() != "nan"]
            sym = next((c for c in cells if c in want), None)
            if not sym or sym in seen:
                continue
            monies = [m for m in (_num(c) for c in cells
                                  if str(c).strip().startswith("$")) if m is not None]
            if not monies:
                continue
            seen.add(sym)
            rows.append({"Sym": sym, "Maint": monies[0],
                         "Day": monies[1] if len(monies) > 1 else None})
    return rows


def main():
    now = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    td = resolve_tradedate()
    print(f"tradeDate resolved: {td}")

    curves = {}
    for name, pid in CME_PRODUCTS.items():
        rows = fetch_cme(pid, td) if td else []
        if rows:
            curves[name] = rows
            print(f"  CME {name}: {len(rows)} rows")
    for name, root in BARCHART_SOFTS.items():
        rows = fetch_barchart(root)
        if rows:
            curves[name] = rows
            print(f"  Barchart {name}: {len(rows)} rows")

    (OUT / "curves.json").write_text(json.dumps(
        {"generated": now, "tradeDate": td, "curves": curves}, indent=1))
    print(f"wrote data/curves.json ({len(curves)} curves)")

    margins = fetch_margins()
    (OUT / "margins.json").write_text(json.dumps(
        {"generated": now, "date": str(dt.date.today()), "rows": margins}, indent=1))
    print(f"wrote data/margins.json ({len(margins)} rows)")


if __name__ == "__main__":
    main()
