# ARCHITECTURE

## FILES

app.py — Streamlit terminal; ten tabs, cached data functions, refresh/staleness shell | imports: sk_amp, sk_board, sk_calendar, sk_curve, sk_export, sk_knowledge, sk_margins, sk_portfolio, sk_render, sk_sources, sk_spreads, sk_technical, sk_ui, sk_universe | called by: —

build.py — CI build of the static site; fetches once, writes every JSON payload | imports: sk_amp, sk_board, sk_curve, sk_knowledge, sk_margins, sk_sources, sk_spreads, sk_technical, sk_universe | called by: —

pull.py — CLI refresh of one dataset without a full build | imports: sk_amp, sk_curve, sk_margins, sk_sources | called by: —

diag_margins.py — Streamlit diagnostic for an empty Margins tab | imports: sk_sources, sk_universe | called by: —

sakata_stats.py — spread and outright statistics; pure numpy/pandas | imports: — | called by: sk_portfolio, sk_spreads

sk_amp.py — scrapes AMP margin tables | imports: sk_universe | called by: app, build, pull

sk_board.py — Board tab data: last price and the calendar-period ladder | imports: sk_fmt, sk_universe | called by: app, build

sk_calendar.py — Calendar tab data: scheduled events, roll dates, expiries | imports: sk_universe | called by: app

sk_charts.py — every SVG the site draws | imports: sk_ui | called by: sk_render

sk_curve.py — term structure, roll, annualised carry from CME settlements | imports: sk_fmt, sk_universe | called by: app, build, pull

sk_export.py — provider-neutral Briefing export; cleans chart series and serialises canonical JSON plus LLM-ready Markdown | imports: — | called by: app

sk_fmt.py — JSON number formatting shared by tab modules | imports: — | called by: sk_board, sk_curve, sk_margins, sk_technical

sk_knowledge.py — hand-maintained per-contract notes; no fetch | imports: — | called by: build, sk_render

sk_margins.py — margin vs notional, realised vol, vol percentiles, multi-bar vol grid | imports: sk_fmt, sk_universe | called by: app, build, pull, sk_render

sk_portfolio.py — basket weights by search; plan, turnover, hold stats | imports: sakata_stats | called by: app

sk_render.py — HTML for every tab | imports: sk_charts, sk_knowledge, sk_margins, sk_ui, sk_universe | called by: app

sk_sources.py — every network call: Yahoo OHLC, CME, resampling | imports: sk_universe | called by: app, build, diag_margins, pull

sk_spreads.py — spread field: one ranked table and a chart set per window | imports: sakata_stats, sk_universe | called by: app, build

sk_technical.py — Range Levels across the five-rung ladder | imports: sk_fmt, sk_universe | called by: app, build

sk_ui.py — CSS tokens, theme, and HTML primitives (table, cell, eyebrow, swatch, note) | imports: — | called by: app, sk_charts, sk_render

sk_universe.py — instrument list, sectors, groups, multipliers, CME product ids | imports: — | called by: app, build, diag_margins, sk_amp, sk_board, sk_calendar, sk_curve, sk_margins, sk_render, sk_sources, sk_spreads, sk_technical

## ENTRY POINTS

`streamlit run app.py` — the terminal. `python build.py` — the static site in CI.
`python pull.py <dataset>` — refresh one payload. `streamlit run diag_margins.py` — margin source check.

1. `sk_universe` defines the 19 instruments; every module derives its symbol list from it.
2. `sk_sources.fetch_ohlc` pulls 15m/60d, 1h/730d, 1d/10y in batched requests; 4h and 1wk are resampled from those.
3. Tab modules (`sk_board`, `sk_margins`, `sk_spreads`, `sk_technical`, `sk_curve`, `sk_calendar`, `sk_portfolio`) turn frames into plain dicts.
4. `sk_render` turns those dicts into HTML using `sk_ui` primitives and `sk_charts` SVG.
5. `app.py` wraps steps 2–4 in `st.cache_data` and pipes the HTML through `UI.md`; `build.py` writes the same dicts to JSON for the static site.

## TOUCH GROUPS

Margins and vol grid: sk_margins.py, sk_render.py, app.py
Universe changes: sk_universe.py, sk_sources.py, sk_amp.py, build.py
Styling and table markup: sk_ui.py, site/sakata.css, sk_render.py, sk_charts.py
Spreads and portfolio: sakata_stats.py, sk_spreads.py, sk_portfolio.py, sk_render.py, app.py
Data fetching: sk_sources.py, sk_amp.py, sk_curve.py, pull.py, build.py, diag_margins.py
Tab wiring: app.py, sk_render.py
Briefing export: app.py, sk_export.py
Static site: build.py, sk_knowledge.py, site/
Board tab: sk_board.py, sk_render.py, app.py
Technical tab: sk_technical.py, sk_render.py, app.py
Calendar tab: sk_calendar.py, sk_render.py, app.py
Number formatting: sk_fmt.py, sk_board.py, sk_curve.py, sk_margins.py, sk_technical.py

## WARNINGS

app.py:106 reloads sakata_stats and sk_fmt by string name — not an import edge.
Update that list when module names change.
