"""AMP margin scraping, rewritten to read the table the way a person does.

The old version matched any cell whose text happened to equal one of our
codes, then took the first two dollar figures in that row. That worked when
AMP served one table per product group. It now serves ONE table with section
titles and repeated header rows as data, so a positional rule is guessing.

This tracks the header row instead. When a row reads
    Name, Symbol, CQG Symbol, Exchange, *Maintenance, Day Trading
the column indices are recorded, and every row beneath it is read by column
until the next header appears. A stray dollar figure in a Name cell can no
longer be mistaken for a margin, and the Symbol column is matched exactly,
so MES can never be picked up as ES.

Errors are raised rather than swallowed. fetch_margins previously called
read_html OUTSIDE its try block, so a parse failure propagated to a bare
`except` in the caller and the tab went empty with nothing in the logs —
which is what made this take two rounds to find.
"""
import io
import re

import pandas as pd

import sk_universe as U

AMP_URL = "https://www.ampfutures.com/trading-info/margins"

# Header cells we recognise, lowercased and stripped of punctuation. AMP
# prefixes maintenance with an asterisk and has renamed the day column more
# than once, so match on a stem rather than the full string.
_MAINT = ("maintenance", "maint")
_DAY = ("day trading", "day trade", "daytrading", "intraday")
_SYM = ("symbol",)
_NAME = ("name", "product")


def _norm(x) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(x).strip().lower())


def _money(x):
    """'$2,754.00' -> 2754.0. Returns None for anything that is not money."""
    s = str(x).strip()
    if not s.startswith("$"):
        return None
    try:
        return float(s.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _is_header(cells) -> bool:
    n = [_norm(c) for c in cells]
    has_sym = any(v in _SYM for v in n)
    has_maint = any(any(v.startswith(m) for m in _MAINT) for v in n)
    return has_sym and has_maint


def _columns(cells) -> dict:
    """Map role -> column index from a header row."""
    idx = {}
    for i, c in enumerate(cells):
        v = _norm(c)
        if not v:
            continue
        if v in _SYM and "sym" not in idx:
            idx["sym"] = i
        elif any(v.startswith(m) for m in _MAINT) and "maint" not in idx:
            idx["maint"] = i
        elif any(v.startswith(d) for d in _DAY) and "day" not in idx:
            idx["day"] = i
        elif v in _NAME and "name" not in idx:
            idx["name"] = i
    return idx


def parse_amp(html: str) -> dict:
    """{code: {maint, day, name}} for every code in the universe.

    Raises on a parse failure. The caller decides what to do about it; the
    one thing that must not happen is an empty dict that looks like a clean
    result.
    """
    tables = pd.read_html(io.StringIO(html))
    if not tables:
        raise ValueError("no tables in the AMP page")

    want = set(U.CODES)
    out, cols = {}, {}
    for t in tables:
        for row in t.itertuples(index=False):
            cells = ["" if pd.isna(c) else str(c).strip() for c in row]
            if _is_header(cells):
                cols = _columns(cells)
                continue
            if "sym" not in cols or "maint" not in cols:
                continue
            if cols["sym"] >= len(cells):
                continue
            sym = cells[cols["sym"]].strip().upper()
            if sym not in want or sym in out:
                continue
            maint = _money(cells[cols["maint"]]) if cols["maint"] < len(cells) else None
            day = (_money(cells[cols["day"]])
                   if "day" in cols and cols["day"] < len(cells) else None)
            if maint is None:
                continue
            out[sym] = {"maint": maint, "day": day,
                        "name": (cells[cols["name"]]
                                 if "name" in cols and cols["name"] < len(cells)
                                 else "")}
    if not out:
        raise ValueError(
            f"AMP page parsed ({len(tables)} tables) but no symbols matched — "
            "the layout has changed")
    return out


CME_CSV = "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv"
# AMP's table stops short of crypto, so these two come from the exchange
# directly. Their clearing codes happen to match the Globex tickers, which is
# not true of most CME products — corn clears as C, not ZC — so this shortcut
# works here and would not generalise.
CME_ONLY = {"BTC": "BTC", "ETH": "ETH"}


def fetch_cme_crypto(session) -> dict:
    """{code: {maint, day}} for the contracts AMP does not carry.

    The file is tiered by contract period, several rows per product. Taking
    the first row would pick whichever tier happens to sort first, so this
    takes the modal maintenance instead — the level that applies across most
    of the curve rather than to an expiring or balance-of-month tier.
    """
    out = {}
    try:
        txt = session.get(CME_CSV, timeout=25).text
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return out
    codes = df["Product Code"].astype(str).str.strip().str.upper()
    for ours, theirs in CME_ONLY.items():
        hit = df[codes == theirs]
        if hit.empty:
            continue
        maint = pd.to_numeric(hit["Maintenance"], errors="coerce").dropna()
        if maint.empty:
            continue
        out[ours] = {"maint": float(maint.mode().iloc[0]), "day": None,
                     "name": str(hit.iloc[0]["Product Name"])[:40]}
    return out


def fetch_amp(session) -> dict:
    """One request, one parse, errors visible. `session` is sk_sources.session."""
    r = session.get(AMP_URL, timeout=25)
    r.raise_for_status()
    out = parse_amp(r.text)
    # Crypto last, and only for what AMP did not already provide.
    for code, rec in fetch_cme_crypto(session).items():
        out.setdefault(code, rec)
    return out
