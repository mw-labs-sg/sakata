# Sakata

A futures terminal that is entirely static. GitHub Actions fetches, computes and
commits JSON; GitHub Pages serves an HTML/CSS/JS viewer over it. No server, no
Streamlit, no cold start, and nothing that needs a laptop to be awake.

**Live:** https://mw-labs-sg.github.io/sakata/

## Why static

Yahoo, CME, AMP and Trading Economics all serve residential and CI IPs while
rate-limiting hosted-app ranges. A hosted Streamlit app therefore came back
empty on exactly the tabs that mattered. Fetching on a runner and publishing the
result removes the whole class of problem, and the page loads instantly on a
phone.

## Layout

```
build.py            orchestrator: fetch -> compute -> docs/
sk_universe.py      the instrument universe. Add an instrument HERE and only here.
sk_sources.py       every network call (Yahoo, CME, AMP, Trading Economics, RSS)
sk_tabs.py          compute for Board, Technical, Curve, Margins
sk_spreads.py       the spread/outright field, per calendar period
sakata_stats.py     the statistics themselves (Sharpe, ER, alignment, ranking)
site/               index.html · sakata.css · sakata.js   (the shell, edited by hand)
docs/               PUBLISHED OUTPUT — built, committed, never edited by hand
.github/workflows/  the build schedule
```

## Run it

```bash
pip install -r requirements.txt

python build.py --dry          # synthetic prices, no network — tests the whole path
python build.py                # live
python build.py --skip news,curve

python -m http.server -d docs 8000   # then open http://localhost:8000
```

`--dry` matters: it exercises fetch, compute, JSON and shell copy without
touching a single external host, so a rendering change can be checked in
seconds and offline.

## Tabs

| Tab       | Source                          | Notes |
|-----------|---------------------------------|-------|
| Board     | Yahoo daily closes              | Day/WTD/MTD/QTD/YTD, financials and commodities side by side |
| Technical | Yahoo 1H/4H/1D/1W               | Range Levels across a five-rung ladder, bias −3..+3, drill-down candles |
| Spreads   | Yahoo 1H/1D                     | Outrights and pairs ranked in one field, per period, with the digest |
| Curve     | CME settlements                 | Term structure, roll and annualised carry, ranked scanner |
| Margins   | AMP + CME outright file         | Margin vs notional, vol and daily range |
| Events    | *computed in the browser*       | Pure calendar rules, so they stay correct even if the build is stale |
| News      | Trading Economics + CoinDesk    | Overnight commentary, built to paste into an LLM |

## Adding an instrument

Add one row to `INSTRUMENTS` in `sk_universe.py`. If it has a CME curve, add its
`productId` to `CME_PRODUCT`; for the Margins tab add a contract multiplier to
`MULT`. Board, Technical, Spreads and Events pick it up with no further edits.

## Pages settings

Settings → Pages → Source: *Deploy from a branch*, branch `main`, folder
`/docs`.
