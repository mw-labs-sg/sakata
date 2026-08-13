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

One file per tab, on both sides. A tab is a Python module that computes it
and a JS file that draws it, and nothing else needs opening to change one.

```
build.py            orchestrator: fetch -> compute -> docs/
pull.py             refresh ONE dataset by hand, no build, no Action
sk_universe.py      the instrument universe. Add an instrument HERE and only here.
sk_sources.py       every network call (Yahoo, CME, AMP)
sk_fmt.py           JSON number formatting shared by the tab modules
sk_board.py         Board
sk_technical.py     Technical — Range Levels, bias, reward:risk
sk_spreads.py       Spreads — the ranked field across nine windows
sk_curve.py         Curve
sk_margins.py       Margins
sk_knowledge.py     Knowledge — five drivers per contract, hand-maintained
sakata_stats.py     the statistics themselves (Sharpe, ER, alignment, ranking)

site/               the shell, edited by hand
  index.html        script order lives here
  sakata.css        every colour, as tokens, light and dark
  js/core.js        state, routing, palette, table helpers
  js/charts.js      bar, line and candle primitives
  js/<tab>.js       one per tab: board, technical, spreads, curve,
                    margins, events, knowledge, news
  js/boot.js        runs last

docs/               PUBLISHED OUTPUT — built, committed, never edited by hand
.github/workflows/  the build schedule
```

Events and News have no Python module. Events is pure calendar arithmetic done
in the browser, so it stays correct when the build is days old; News is fetched
live from the page on every load.

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
