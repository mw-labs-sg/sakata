"""Bridge between Sakata's instrument universe and the ported SANPO modules.

The spreads/portfolio code came out of SANPO, where it imported FUTURES_GROUPS,
SYMBOL_NAMES, THEMES, FONTS and clean_symbol from a `config` module. Rather than
carry SANPO's config across, this derives everything from Sakata's own SECTORS
so there is still exactly one place (common.py) that defines the universe.
"""
from common import SECTORS

FONTS = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"

# ---------------------------------------------------------------- universe
# sector -> [yahoo ticker, ...]   (spread groups need >= 2 members)
FUTURES_GROUPS = {
    sector: [t for t, _dec in members.values()]
    for sector, members in SECTORS.items()
}

# One representative per sector — the cross-asset group, where the most
# interesting spreads usually live.
MACRO = ["ES=F", "ZN=F", "6E=F", "CL=F", "GC=F", "HG=F", "ZC=F", "BTC-USD"]
FUTURES_GROUPS["Macro"] = MACRO

# ticker -> display code, e.g. "ES=F" -> "ES"
SYMBOL_NAMES = {
    ticker: name.split()[0]
    for members in SECTORS.values()
    for name, (ticker, _dec) in members.items()
}
# ticker -> full label, e.g. "ES=F" -> "ES  S&P 500"  (used in tooltips/captions)
SYMBOL_LABELS = {
    ticker: " ".join(name.split())
    for members in SECTORS.values()
    for name, (ticker, _dec) in members.items()
}


def clean_symbol(sym: str) -> str:
    """Fallback pretty-printer for tickers outside the Sakata universe."""
    return (str(sym).replace("=F", "").replace("=X", "")
            .replace(".SI", "").replace("-USD", ""))


# ---------------------------------------------------------------- theme
# Sakata is light-only. Both keys point at the same palette so the ported
# code's `THEMES.get(name, THEMES['Dark'])` fallback keeps working untouched.
_LIGHT = {
    "pos":       "#16a34a",   # positive numbers
    "neg":       "#dc2626",   # negative numbers
    "long":      "#0d9488",   # long leg (teal — matches the Curve tab)
    "short":     "#f59e0b",   # short leg (amber — matches the logo bars)
    "text":      "#334155",
    "text2":     "#64748b",
    "muted":     "#94a3b8",
    "bg3":       "#f8fafc",   # table header / panel fill
    "border":    "#e2e8f0",
    "plot_bg":   "#ffffff",
    "grid":      "#eef2f6",
    "axis_line": "#e2e8f0",
    "tick":      "#94a3b8",
}
THEMES = {"Light": _LIGHT, "Dark": _LIGHT}
