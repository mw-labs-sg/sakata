"""diag_margins.py — why is the Margins tab empty?

A failed scrape and a broken parser look identical from the outside: both end
with no rows — a 403, a timeout, a page restyle or a missing lxml are four
problems with four different fixes. sk_amp.fetch_amp raises rather than
swallowing, so the app now names the reason itself; this page is for when you
want to see each stage separately.

This reports each stage separately: did the request complete, what came back,
did pandas find tables in it, and did any of them contain our symbols. Drop it
in as a Streamlit page or run it locally:

    streamlit run diag_margins.py
"""
import io
import time

import pandas as pd
import streamlit as st

import sk_sources as S
import sk_universe as U

st.set_page_config(page_title="Margin source diagnostic", layout="wide")
st.title("Margin source diagnostic")
st.caption("Run this from the app so it uses the same network path as the "
           "real fetch. Results from a laptop prove nothing about what "
           "Streamlit's IP range can reach.")

SOURCES = {
    "AMP margins": "https://www.ampfutures.com/trading-info/margins",
    "CME OUTRIGHT.csv":
        "https://www.cmegroup.com/CmeWS/mvc/Margins/OUTRIGHT.csv",
    # Resolved rather than hardcoded: a frozen date makes a working endpoint
    # look dead the moment it rolls past.
    "CME settlements probe":
        "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/"
        f"Settlements/425/FUT?tradeDate={S.resolve_tradedate() or ''}",
}

rows = []
bodies = {}
for name, url in SOURCES.items():
    rec = {"source": name, "status": "—", "bytes": 0, "secs": None,
           "note": ""}
    t0 = time.time()
    try:
        r = S.session().get(url, timeout=25)
        rec["status"] = r.status_code
        text = r.text
        rec["bytes"] = len(text)
        bodies[name] = text
        # A 200 with a Cloudflare interstitial is a block wearing a success
        # code, so look at the body rather than trusting the status alone.
        low = text[:4000].lower()
        for flag in ("just a moment", "cf-browser-verification", "captcha",
                     "access denied", "attention required"):
            if flag in low:
                rec["note"] = f"body looks like a challenge page ({flag})"
                break
    except Exception as e:
        rec["status"] = "EXC"
        rec["note"] = f"{type(e).__name__}: {str(e)[:70]}"
    rec["secs"] = round(time.time() - t0, 1)
    rows.append(rec)

st.subheader("1 · Can we reach it")
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ------------------------------------------------------------------- AMP
st.subheader("2 · AMP — does the parse still work")
html = bodies.get("AMP margins", "")
if not html:
    st.error("Nothing came back, so there is nothing to parse. The problem is "
             "the request, not the parser.")
else:
    try:
        tables = pd.read_html(io.StringIO(html))
        st.write(f"pandas found **{len(tables)}** tables in "
                 f"{len(html):,} bytes.")
        want = set(U.CODES)
        hits, sample = {}, None
        for i, t in enumerate(tables):
            found = set()
            for row in t.itertuples(index=False):
                cells = [str(c).strip() for c in row]
                found |= (want & set(cells))
            if found:
                hits[i] = sorted(found)
                if sample is None:
                    sample = t.head(6)
        if hits:
            st.success(f"Symbols matched in {len(hits)} table(s): "
                       + ", ".join(f"#{i} ({len(v)} codes)"
                                   for i, v in hits.items()))
            st.dataframe(sample, use_container_width=True)
            st.caption("If this works, AMP is not blocked and the failure is "
                       "in the parser — check sk_amp._is_header and _columns "
                       "against the header row shown above.")
        else:
            st.warning("Tables parsed, but not one contained our symbols. "
                       "That is a page restyle, not a block — the fix is the "
                       "parser.")
            if tables:
                st.dataframe(tables[0].head(8), use_container_width=True)
    except ImportError as e:
        st.error(f"read_html needs lxml, which is not installed here: {e}")
    except Exception as e:
        st.error(f"{type(e).__name__}: {str(e)[:120]}")

# ------------------------------------------------------------------- CME
st.subheader("3 · CME — coverage for our 19")
csv = bodies.get("CME OUTRIGHT.csv", "")
if not csv or not csv.lstrip().startswith('"Exchange"'):
    st.error("No usable CSV came back.")
else:
    df = pd.read_csv(io.StringIO(csv))
    st.write(f"**{len(df):,}** rows, "
             f"**{df['Product Code'].nunique():,}** distinct product codes.")
    # CME clearing codes are not Globex tickers: corn clears as C, not ZC.
    GUESS = {"ES": "ES", "NQ": "NQ", "NKD": "NK", "ZB": "ZB", "ZN": "ZN",
             "6E": "EC", "6J": "JY", "BTC": "BTC", "ETH": "ETH", "CL": "CL",
             "NG": "NG", "GC": "GC", "SI": "SI", "HG": "HG", "ZC": "C",
             "ZW": "W", "ZS": "S", "SB": "YO", "KC": "KT"}
    codes = df["Product Code"].astype(str).str.strip().str.upper()
    out = []
    for ours, theirs in GUESS.items():
        hit = df[codes == theirs.upper()]
        out.append({
            "ours": ours, "cme code": theirs, "rows": len(hit),
            "tiers": len(hit),
            "maint range": (f'{hit["Maintenance"].min()} – '
                            f'{hit["Maintenance"].max()}') if len(hit) else "—",
            "name": (str(hit.iloc[0]["Product Name"])[:34]
                     if len(hit) else "NOT FOUND"),
        })
    res = pd.DataFrame(out)
    st.dataframe(res, hide_index=True, use_container_width=True)
    miss = res[res["rows"] == 0]["ours"].tolist()
    st.caption(
        f"Missing: {', '.join(miss) if miss else 'none'}. "
        "Multiple tiers per product is expected — margin varies by contract "
        "period, so picking row 0 is wrong; the front month's tier is the one "
        "that matters. SB and KC are ICE contracts, so any NYMEX match is a "
        "cash-settled lookalike, not what you trade.")
