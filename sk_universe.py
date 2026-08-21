"""Sakata — the instrument universe. Single source of truth for the whole build.

Every other module derives its symbol list from here. Nothing in this file
imports anything heavier than the standard library, so it is safe to import
from any build step.
"""

# code -> (display name, yahoo ticker, decimals, sector)
INSTRUMENTS = [
    ("ES",  "S&P 500",   "ES=F",    2, "Indices"),
    ("NQ",  "Nasdaq",    "NQ=F",    2, "Indices"),
    ("NKD", "Nikkei",    "NKD=F",   0, "Indices"),
    ("ZB",  "T-Bond",    "ZB=F",    3, "Bonds"),
    ("ZN",  "10Y Note",  "ZN=F",    3, "Bonds"),
    ("6E",  "Euro",      "6E=F",    4, "Currencies"),
    ("6J",  "Yen",       "6J=F",    7, "Currencies"),
    ("BTC", "Bitcoin",   "BTC-USD", 0, "Crypto"),
    ("ETH", "Ether",     "ETH-USD", 2, "Crypto"),
    ("CL",  "Crude",     "CL=F",    2, "Energy"),
    ("NG",  "Nat Gas",   "NG=F",    3, "Energy"),
    ("GC",  "Gold",      "GC=F",    1, "Metals"),
    ("SI",  "Silver",    "SI=F",    3, "Metals"),
    ("HG",  "Copper",    "HG=F",    4, "Metals"),
    ("ZC",  "Corn",      "ZC=F",    2, "Grains"),
    ("ZW",  "Wheat",     "ZW=F",    2, "Grains"),
    ("ZS",  "Soybean",   "ZS=F",    2, "Grains"),
    ("SB",  "Sugar",     "SB=F",    2, "Softs"),
    ("KC",  "Coffee",    "KC=F",    2, "Softs"),
]

GROUPS = {
    "Financials":  ["Indices", "Bonds", "Currencies", "Crypto"],
    "Commodities": ["Energy", "Metals", "Grains", "Softs"],
}
GROUP_OF = {sec: g for g, secs in GROUPS.items() for sec in secs}

CODES = [i[0] for i in INSTRUMENTS]
TICKERS = [i[2] for i in INSTRUMENTS]
NAME = {i[0]: i[1] for i in INSTRUMENTS}
TICKER = {i[0]: i[2] for i in INSTRUMENTS}
DEC = {i[0]: i[3] for i in INSTRUMENTS}
SECTOR = {i[0]: i[4] for i in INSTRUMENTS}

# CME productIds for the settlement/curve endpoint. Missing = no curve.
CME_PRODUCT = {
    "ES": 133, "NQ": 146, "ZB": 307, "ZN": 316, "6E": 58, "6J": 69,
    "BTC": 8478, "ETH": 8995, "CL": 425, "NG": 444, "GC": 437, "SI": 458,
    "HG": 438, "ZC": 300, "ZW": 323, "ZS": 320,
}

# Contract multiplier folded with unit conversion: notional = price * MULT.
MULT = {
    "ES": 50, "NQ": 20, "NKD": 5, "ZB": 1000, "ZN": 1000, "6E": 125000,
    "6J": 12500000, "BTC": 5, "ETH": 50, "CL": 1000, "NG": 10000, "GC": 100,
    "SI": 5000, "HG": 25000, "ZC": 50, "ZW": 50, "ZS": 50, "SB": 1120,
    "KC": 375,
}

# The small contract, where one exists: (ticker, multiplier, divisor).
#
# This is what makes a computed ratio executable. A spread sized 1.6 : 1 cannot
# be traded — you round to 2 : 1 and carry a hedge that is 25% off — but the
# same risk in micros is 8 : 5, or in a mixed ticket often 1 : 3 of something
# smaller. The divisor is only carried so the arithmetic can be checked on
# sight: MULT[code] / divisor must equal the multiplier.
#
# VERIFY THESE AGAINST CME BEFORE TRADING OFF THEM. They are transcribed
# specifications, not fetched, and a wrong multiplier here is a wrong hedge —
# the failure is silent and it is in the direction of your money. ZB, ZN, NKD,
# SB and KC have no micro on the same underlying, so they size in standards.
MICRO = {
    "ES":  ("MES", 5,        10),    # Micro E-mini S&P 500, $5 x index
    "NQ":  ("MNQ", 2,        10),    # Micro E-mini Nasdaq-100, $2 x index
    "BTC": ("MBT", 0.1,      50),    # Micro Bitcoin, 0.1 BTC
    "ETH": ("MET", 0.1,     500),    # Micro Ether, 0.1 ETH
    "GC":  ("MGC", 10,       10),    # Micro Gold, 10 troy oz
    "SI":  ("SIL", 1000,      5),    # Micro Silver, 1,000 troy oz
    "HG":  ("MHG", 2500,     10),    # Micro Copper, 2,500 lbs
    "CL":  ("MCL", 100,      10),    # Micro WTI, 100 barrels
    "6E":  ("M6E", 12500,    10),    # Micro EUR/USD, 12,500 EUR
    "6J":  ("M6J", 1250000,  10),    # Micro JPY/USD, 12,500,000 yen / 10
    "NG":  ("QG",  2500,      4),    # E-mini Nat Gas, 2,500 MMBtu
    "ZC":  ("XC",  10,        5),    # Mini Corn, 1,000 bu
    "ZW":  ("XW",  10,        5),    # Mini Wheat, 1,000 bu
    "ZS":  ("XK",  10,        5),    # Mini Soybean, 1,000 bu
}

# Round-turn cost of ONE contract, all in: broker commission plus exchange,
# clearing and NFA fees. (standard, small) in dollars.
#
# ESTIMATES, AND YOURS WILL DIFFER. Commission is the negotiable part and the
# exchange half moves with rule changes, so these are a plausible retail
# schedule rather than a quote. They are here to answer one question — is a
# fill worth its tickets — and that answer is robust to being 30% out. It is
# not robust to a fee being ten times wrong, so check the ones you trade.
#
# The pattern worth knowing is not the dollar fee, it is the fee against the
# contract's own notional — and the index micros and the crypto micros are not
# the same story at all:
#
#   MES  $1.00 on $38,349   0.26bp    2x its standard
#   MBT  $0.60 on  $7,368   0.81bp    5x its standard
#   MET  $0.60 on    $234  25.63bp   50x its standard, 250x an ES
#
# MES is a TENTH of an ES, so a fee a quarter the size costs about twice as
# much per dollar. MET is a FIVE-HUNDREDTH of an ETH — 0.1 ether, a couple of
# hundred dollars — so any per-contract fee at all is enormous against it.
# That is why closing an ether leg to the last percent in micros costs real
# money while doing the same in MES costs almost nothing.
FEES = {
    "ES":  (4.00, 1.00), "NQ":  (4.00, 1.00), "NKD": (4.50, None),
    "ZB":  (3.20, None), "ZN":  (3.20, None),
    "6E":  (3.60, 0.90), "6J":  (3.60, 0.90),
    "BTC": (6.00, 0.60), "ETH": (6.00, 0.60),
    "CL":  (4.00, 0.90), "NG":  (4.00, 1.60),
    "GC":  (4.00, 1.00), "SI":  (4.00, 1.00), "HG": (4.00, 1.00),
    "ZC":  (4.40, 1.60), "ZW":  (4.40, 1.60), "ZS": (4.40, 1.60),
    "SB":  (5.00, None), "KC":  (5.00, None),
}

# What the fee schedule is scaled by. Retail is the table above; a funded or
# professional account clears a good deal cheaper, and zero is for reading the
# portfolio without them.
FEE_TIERS = {"Retail": 1.0, "Pro": 0.45, "None": 0.0}


# Trading Economics commentary pages, per instrument.
# Crypto is deliberately absent. Their btcusd/ethusd pages carry a commentary
# paragraph that goes weeks without changing — a July paragraph was still
# showing in mid-August — so the tab would present three-week-old text with
# today's layout around it. Stale commentary that looks current is worse than
# no commentary, and the Drivers tab already says what moves the two of them.
TE_PAGE = {
    "ES":  "https://tradingeconomics.com/united-states/stock-market",
    "NKD": "https://tradingeconomics.com/japan/stock-market",
    "ZB":  "https://tradingeconomics.com/united-states/government-bond-yield",
    "6E":  "https://tradingeconomics.com/euro-area/currency",
    "6J":  "https://tradingeconomics.com/japan/currency",
    "CL":  "https://tradingeconomics.com/commodity/crude-oil",
    "NG":  "https://tradingeconomics.com/commodity/natural-gas",
    "GC":  "https://tradingeconomics.com/commodity/gold",
    "SI":  "https://tradingeconomics.com/commodity/silver",
    "HG":  "https://tradingeconomics.com/commodity/copper",
    "ZC":  "https://tradingeconomics.com/commodity/corn",
    "ZW":  "https://tradingeconomics.com/commodity/wheat",
    "ZS":  "https://tradingeconomics.com/commodity/soybeans",
    "SB":  "https://tradingeconomics.com/commodity/sugar",
    "KC":  "https://tradingeconomics.com/commodity/coffee",
}

# Range Levels ladder: horizon -> bar, calendar segment, history to request.
LADDER = {
    "Day":   dict(bar="1h",  seg="D", period="730d", note="1H bars"),
    "Week":  dict(bar="1h",  seg="W", period="730d", note="1H bars"),
    "Month": dict(bar="4h",  seg="M", period="730d", note="4H bars"),
    "Qtr":   dict(bar="1d",  seg="Q", period="10y",  note="1D bars"),
    "Year":  dict(bar="1wk", seg="Y", period="max",  note="1W bars"),
}
LADDER_ORDER = ["Day", "Week", "Month", "Qtr", "Year"]
