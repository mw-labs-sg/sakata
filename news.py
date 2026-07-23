"""News tab — overnight commentary blurb per market from Trading Economics."""
import streamlit as st

from common import _session


# News: overnight commentary blurb scraped per market from Trading Economics.
TE_NEWS = {
    # Indices
    "ES  S&P 500":  "https://tradingeconomics.com/united-states/stock-market",
    "NKD  Nikkei":  "https://tradingeconomics.com/japan/stock-market",
    # Bonds
    "ZB  T-Bond":   "https://tradingeconomics.com/united-states/government-bond-yield",
    # Currencies
    "6E  Euro":     "https://tradingeconomics.com/euro-area/currency",
    "6J  Yen":      "https://tradingeconomics.com/japan/currency",
    # Crypto — note the :cur URL pattern, not /commodity/
    "BTC  Bitcoin": "https://tradingeconomics.com/btcusd:cur",
    # Energy
    "CL  Crude":    "https://tradingeconomics.com/commodity/crude-oil",
    "NG  Nat Gas":  "https://tradingeconomics.com/commodity/natural-gas",
    # Metals
    "GC  Gold":     "https://tradingeconomics.com/commodity/gold",
    "SI  Silver":   "https://tradingeconomics.com/commodity/silver",
    "HG  Copper":   "https://tradingeconomics.com/commodity/copper",
    # Grains
    "ZC  Corn":     "https://tradingeconomics.com/commodity/corn",
    "ZW  Wheat":    "https://tradingeconomics.com/commodity/wheat",
    "ZS  Soybean":  "https://tradingeconomics.com/commodity/soybeans",
    # Softs
    "SB  Sugar":    "https://tradingeconomics.com/commodity/sugar",
    "KC  Coffee":   "https://tradingeconomics.com/commodity/coffee",
}


@st.cache_data(ttl=900, show_spinner=False)
def get_te_commentary(url: str) -> dict:
    """Return the overnight commentary blurb (+ headline, date, link) from a TE
    market page — the body of the first /news/<id> item, which is the same text
    as the page's lead summary paragraph."""
    import re
    html = _session.get(url, timeout=25).text
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"headline": "", "blurb": "", "date": "", "url": url,
                "err": "pip install beautifulsoup4"}
    soup = BeautifulSoup(html, "html.parser")

    anchor = None
    for a in soup.select("a[href*='/news/']"):
        if re.search(r"/news/\d+", a.get("href", "")) and a.get_text(strip=True):
            anchor = a
            break
    if anchor is None:
        return {"headline": "", "blurb": "", "date": "", "url": url}

    headline = anchor.get_text(strip=True)
    href = anchor.get("href", "")
    link = href if href.startswith("http") else "https://tradingeconomics.com" + href

    blurb, date, node = "", "", anchor
    for _ in range(5):          # climb until one item is bracketed by headline..date
        node = node.find_parent()
        if node is None:
            break
        txt = node.get_text(" ", strip=True)
        i = txt.find(headline)
        after = txt[i + len(headline):] if i >= 0 else txt
        if (dm := re.search(r"(20\d\d-\d\d-\d\d)", after)) and dm.start() > 40:
            blurb = after[:dm.start()].strip()
            date = dm.group(1)
            break
    return {"headline": headline, "blurb": blurb, "date": date, "url": link}


def render_news() -> None:
    st.caption(
        "Overnight commentary per market — the lead blurb from each Trading Economics "
        "page. Cached 15 min. Locally your chrome session clears TE's bot wall; a blank "
        "means the datacenter IP. Built to copy wholesale into an LLM."
    )
    all_labels = list(TE_NEWS)
    c1, c2 = st.columns([5, 1])
    with c1:
        picks = st.multiselect("Markets", all_labels, default=all_labels,
                               label_visibility="collapsed", key="news_pick")
    with c2:
        if st.button("Refresh", key="rn"):
            get_te_commentary.clear()
            st.rerun()
    if not picks:
        st.info("Pick at least one market."); return

    with st.spinner("Fetching commentary…"):
        for label in picks:
            st.markdown(f"##### {label}")
            try:
                d = get_te_commentary(TE_NEWS[label])
            except Exception as e:  # noqa: BLE001
                st.caption(f"— fetch failed: {str(e)[:60]}")
                st.markdown("---")
                continue
            if not d.get("blurb"):
                st.caption(f"— {d.get('err') or 'nothing parsed (likely bot-blocked on this IP)'}")
                st.markdown("---")
                continue
            st.markdown(d["blurb"])
            if d.get("date"):
                st.markdown(f"<span style='color:#94a3b8;font-size:11px'>{d['date']}</span>",
                            unsafe_allow_html=True)
            st.markdown("---")
