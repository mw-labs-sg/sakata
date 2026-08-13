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
SECTOR_ORDER = [s for secs in GROUPS.values() for s in secs]
GROUP_OF = {sec: g for g, secs in GROUPS.items() for sec in secs}

CODES = [i[0] for i in INSTRUMENTS]
TICKERS = [i[2] for i in INSTRUMENTS]
NAME = {i[0]: i[1] for i in INSTRUMENTS}
TICKER = {i[0]: i[2] for i in INSTRUMENTS}
CODE_OF = {i[2]: i[0] for i in INSTRUMENTS}
DEC = {i[0]: i[3] for i in INSTRUMENTS}
SECTOR = {i[0]: i[4] for i in INSTRUMENTS}
LABEL = {i[0]: f"{i[0]}  {i[1]}" for i in INSTRUMENTS}

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

# Trading Economics commentary pages, per instrument.
TE_PAGE = {
    "ES":  "https://tradingeconomics.com/united-states/stock-market",
    "NKD": "https://tradingeconomics.com/japan/stock-market",
    "ZB":  "https://tradingeconomics.com/united-states/government-bond-yield",
    "6E":  "https://tradingeconomics.com/euro-area/currency",
    "6J":  "https://tradingeconomics.com/japan/currency",
    "BTC": "https://tradingeconomics.com/btcusd:cur",
    "ETH": "https://tradingeconomics.com/ethusd:cur",
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
