"""Sakata — what actually moves each contract.

Five drivers per instrument, ordered roughly by how often they set the tone
rather than by magnitude: a driver that matters enormously twice a decade sits
below one that matters most weeks. These are hand-maintained, not derived —
the point is a standing frame to read the tape against, so it should change
only when the structure of a market changes.

Each entry is (headline, mechanism). Keep mechanisms to one clause and say
which way it pushes; a driver you cannot sign is not a driver, it is a topic.
"""

DRIVERS = {
# ---------------------------------------------------------------- indices
"ES": [
 ("Fed path and real yields", "Discount rate for every cash flow; rising real yields compress multiples before they dent earnings."),
 ("Earnings and margin breadth", "Index EPS is top-heavy — margin direction at a handful of megacaps outweighs the median company."),
 ("Financial conditions and credit", "Spreads and the dollar tighten or loosen conditions faster than policy does; equities follow conditions, not the funds rate."),
 ("Growth data", "Payrolls, ISM and claims decide whether a slowdown is priced as disinflation or as a profits recession."),
 ("Positioning and flows", "Buybacks, vol-control and dealer gamma set the path between catalysts and explain drift that has no news attached."),
],
"NQ": [
 ("Long-duration rate sensitivity", "Cash flows sit further out than ES, so the same yield move hits harder — the ES/NQ spread is a rates trade."),
 ("AI capex cycle", "Hyperscaler spending is now a swing factor for revenue and, through depreciation, for forward margins."),
 ("Semiconductor cycle and export policy", "Inventory correction or a controls change repriced the complex several times; it transmits straight to the index."),
 ("Concentration risk", "A handful of names carry the weight, so single-stock news is index news in a way it is not for ES."),
 ("Global growth and the dollar", "Roughly half of revenue is foreign; a strong dollar is a translation headwind on top of a demand one."),
],
"NKD": [
 ("USDJPY", "A weaker yen flatters exporter earnings in yen terms — the index and the currency are close to the same trade."),
 ("BOJ policy and JGB yields", "Normalisation lifts the yen and the discount rate at once, which is why policy meetings dominate."),
 ("Governance reform and buybacks", "TSE pressure on sub-1x book companies has been a persistent domestic bid independent of earnings."),
 ("China demand and global semis", "Heavy machinery, autos and semi equipment weight makes the index a levered read on the regional cycle."),
 ("Foreign investor flows", "Overseas money dominates the marginal trade; allocation shifts move it more than domestic funds do."),
],
# ------------------------------------------------------------------ bonds
"ZB": [
 ("Terminal rate expectations", "The long end trades the average expected policy rate, so it responds to the path years out, not the next meeting."),
 ("Inflation prints", "CPI and PCE set breakevens; the long bond carries the most duration and so the largest response per surprise."),
 ("Supply and deficits", "Refunding announcements and auction tails move the long end independently of the Fed — issuance is the other half of the price."),
 ("Term premium", "QT, foreign demand and issuance duration decide how much extra yield the long end demands for uncertainty."),
 ("Haven flows", "In equity drawdowns the bid appears regardless of fundamentals; the correlation with ES is the trade, and it is not stable."),
],
"ZN": [
 ("Fed cuts priced in the belly", "The ten-year sits where policy expectations and term premium meet — most Fed repricing lands here first."),
 ("Auction demand", "Indirect bidder share and tails signal whether real money or dealers are absorbing supply."),
 ("Growth versus inflation mix", "The belly rallies on weak growth and sells off on sticky inflation; when both arrive the curve does the work."),
 ("Mortgage convexity hedging", "Large yield moves force MBS hedgers to sell into weakness, amplifying the initial move."),
 ("Curve position", "ZN against ZB is a term-premium trade; against the front end it is a policy trade. Know which one you are in."),
],
# ------------------------------------------------------------- currencies
"6E": [
 ("ECB–Fed policy differential", "Two-year spread explains most of the medium-term move; the level of either rate explains little."),
 ("Eurozone growth", "German industrial data and PMIs decide whether the ECB can hold; the euro trades the divergence, not the absolute."),
 ("Terms of trade", "As a net energy importer the bloc's trade balance moves with gas prices — an energy shock is a euro shock."),
 ("Peripheral spreads and politics", "BTP-Bund widening reintroduces redenomination risk premium that no rate differential explains."),
 ("Broad dollar cycle", "EUR is over half of DXY, so it is often the passenger in a dollar move rather than the driver."),
],
"6J": [
 ("US–Japan rate differential", "The cleanest single explanator of USDJPY; the yen is the funding currency and the spread is the carry."),
 ("BOJ normalisation", "Pace of exit from yield control is the domestic swing factor and the source of gap risk."),
 ("Intervention risk", "MOF has acted at extremes; the asymmetry near prior intervention levels matters more than the fundamentals there."),
 ("Risk sentiment and carry unwinds", "Yen strengthens violently when funding trades unwind — it is a volatility hedge that pays when correlations break."),
 ("Energy import bill", "Japan imports nearly all its energy; a crude spike worsens the trade balance and weighs on the yen."),
],
# ----------------------------------------------------------------- crypto
"BTC": [
 ("Spot ETF flows", "Daily creations and redemptions are now the most visible marginal buyer; flow direction leads price more than narrative does."),
 ("Global liquidity and real rates", "Trades as a long-duration risk asset — easing conditions have been the backdrop to every sustained advance."),
 ("Halving supply cycle", "Issuance halves on schedule; the effect is on the margin of new supply, not a mechanical price floor."),
 ("Regulation and market structure", "Custody rules, exchange enforcement and legislation change who is allowed to be a buyer."),
 ("Leverage and funding", "Perp funding and open interest tell you how crowded the move is; liquidation cascades are the mechanism for most fast moves."),
],
"ETH": [
 ("ETH/BTC rotation", "Most of the time ETH is a levered BTC position; the ratio is where anything ETH-specific actually shows up."),
 ("Staking yield and net issuance", "Burn against issuance decides whether supply grows; the staked share decides free float."),
 ("Layer-2 activity and fees", "Rollups moved activity off the base layer, cutting fee revenue and complicating the burn story."),
 ("ETF and staking treatment", "Whether staking is permitted inside a wrapper determines how much institutional demand can actually arrive."),
 ("Leverage and funding", "Same mechanism as BTC but thinner — liquidation cascades travel further."),
],
# ----------------------------------------------------------------- energy
"CL": [
 ("OPEC+ supply policy", "Quota decisions and, more importantly, compliance set the marginal barrel; guidance moves price ahead of the barrels."),
 ("Inventories", "Weekly EIA builds and draws against seasonal norms are the highest-frequency read on whether the market is tight."),
 ("Demand growth", "Chinese imports, US driving season and jet recovery decide the call on OPEC crude."),
 ("US shale supply", "Rig counts, DUC inventory and capital discipline determine how quickly non-OPEC supply answers a price rally."),
 ("Geopolitical risk premium", "Hormuz, Russian export capacity and Middle East escalation add premium that decays fast when nothing happens."),
],
"NG": [
 ("Weather", "Heating and cooling degree days dominate — no other contract on the board is this directly a weather derivative."),
 ("Storage versus five-year average", "The weekly EIA number against the seasonal band is the market's scorecard for surplus or deficit."),
 ("LNG export capacity", "New trains structurally tighten domestic balances; an outage at a terminal is instantly bearish Henry Hub."),
 ("Associated gas production", "Much US supply is a by-product of oil drilling, so gas supply responds to crude economics, not gas prices."),
 ("Coal-to-gas switching", "Power burn is price-elastic at the margin, which puts a soft ceiling and floor on the range."),
],
# ----------------------------------------------------------------- metals
"GC": [
 ("Real yields", "The classic inverse relationship — gold pays no coupon, so the opportunity cost is the real rate."),
 ("Central bank buying", "Official sector accumulation has been large and price-insensitive, which changes the floor more than the ceiling."),
 ("Dollar", "Priced in dollars and bought globally; dollar strength is a headwind independent of rates."),
 ("ETF and futures positioning", "Western investor flows have been the swing factor between official-sector-driven and investor-driven regimes."),
 ("Haven and debasement demand", "Geopolitical escalation and fiscal stress bid gold on days when the rates story says otherwise."),
],
"SI": [
 ("Gold beta", "Roughly follows gold with more volatility; most silver moves are gold moves amplified, so start with the ratio."),
 ("Industrial demand", "Solar, electronics and brazing make about half of demand cyclical — the part gold does not have."),
 ("Mine supply", "Mostly a by-product of copper, lead and zinc mining, so supply barely responds to the silver price."),
 ("Above-ground stocks and lease rates", "Visible LBMA and COMEX inventories plus EFP dislocations flag physical tightness that price alone hides."),
 ("Real rates and dollar", "Same monetary channel as gold, but swamped by the industrial channel when the cycle turns."),
],
"HG": [
 ("China property and grid capex", "Construction and State Grid spending remain the largest single demand block; property starts are the leading read."),
 ("Global manufacturing PMIs", "The classic cycle indicator — copper turns with the manufacturing cycle, which is why it is called Dr Copper."),
 ("Mine supply disruption", "Chilean and Peruvian grades, water constraints and permitting shocks tighten the concentrate market quickly."),
 ("Visible inventories", "LME, SHFE and COMEX stocks together are the cleanest tightness signal; regional divergence flags arbitrage, not shortage."),
 ("Electrification demand", "EVs, renewables and data centre power are a structural bid that shows up in forward curves before spot."),
],
# ----------------------------------------------------------------- grains
"ZC": [
 ("US growing-season weather", "July pollination is the single highest-leverage window; a hot dry stretch then outweighs everything else in the year."),
 ("WASDE acreage and yield", "Monthly USDA revisions to yield and carryout are the scheduled repricing events."),
 ("Ethanol demand and margins", "Roughly a third of the US crop goes to ethanol, tying corn to gasoline cracks and blending policy."),
 ("Export competition", "Brazilian safrinha timing and Black Sea supply decide whether US corn wins the marginal cargo."),
 ("Feed demand", "Cattle-on-feed and hog margins set the largest domestic use category and move slowly but persistently."),
],
"ZW": [
 ("Black Sea supply and war risk", "Russia and Ukraine dominate exportable surplus; corridor and infrastructure news moves price faster than any crop report."),
 ("Northern Hemisphere weather", "Winterkill, spring dryness on the Plains and harvest rain in France or Australia each set separate quality premia."),
 ("Export policy", "Russian export taxes and Indian import or export bans redirect trade flows overnight."),
 ("Stocks-to-use excluding China", "Chinese reserves are not on the market; the ex-China number is the balance that actually prices."),
 ("Quality spreads", "Protein and milling quality separate the classes — the futures contract does not always trade the same wheat you think it does."),
],
"ZS": [
 ("Chinese crush demand", "China buys the majority of traded beans; purchase pace and hog margins there set the tone."),
 ("South American weather", "December to February in Brazil and Argentina now matters more than the US season for global balances."),
 ("Crush margins and biofuel policy", "Renewable diesel demand for soybean oil has decoupled the products from the bean; the crush spread is the real trade."),
 ("US acreage against corn", "The new-crop soy/corn ratio decides spring planting mix and hence the following year's balance."),
 ("Brazilian logistics and basis", "Port queues, truck freight and the real determine how much Brazilian supply reaches the market and at what price."),
],
# ------------------------------------------------------------------ softs
"SB": [
 ("Brazil Centre-South crush", "The largest exporter's fortnightly UNICA data on crush volume and sugar mix is the highest-frequency supply signal."),
 ("Ethanol parity", "Mills switch between sugar and ethanol on relative economics, so crude and Brazilian fuel policy set the sugar supply."),
 ("Indian export policy", "Quota decisions can add or remove millions of tonnes from the export market with no crop change at all."),
 ("Thai and Indian monsoon", "Second and third largest producers; rainfall determines the size of the Asian exportable surplus."),
 ("Brazilian real", "Mills sell in dollars and spend in reais — a weak real incentivises selling and caps rallies."),
],
"KC": [
 ("Brazilian weather", "June to August frost risk and flowering-period rainfall are the two windows that have produced every major spike."),
 ("Vietnam robusta crop", "Robusta supply sets the floor for blenders; a short Vietnamese crop pulls arabica up through substitution."),
 ("Certified stocks", "ICE certified inventory is the visible buffer — low and falling certifieds turn weather scares into squeezes."),
 ("EU deforestation rules", "Compliance requirements bifurcate the market into traceable and untraceable supply, widening differentials."),
 ("Brazilian real and freight", "Producer selling responds to the real; container availability decides how fast physical actually moves."),
],
}
