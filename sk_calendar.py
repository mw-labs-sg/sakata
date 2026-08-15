"""Sakata — the calendar: every scheduled thing that moves the board.

Two changes from the old Events tab. Rules now yield EVERY occurrence in a
horizon rather than only the next one, so the tab answers "what is coming"
rather than "what is next". And market holidays sit in the same stream as
releases, because a shut exchange is a scheduled event that changes what you
can do that day.

Times are stored in US Eastern, which is how every source publishes them, and
converted to Singapore at render. Doing it with zoneinfo rather than a fixed
offset matters: the gap is 12 hours in US summer and 13 in winter, so a
hardcoded +12 is wrong for four months of the year.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import sk_universe as U

ET = ZoneInfo("America/New_York")
SG = ZoneInfo("Asia/Singapore")

FIN = ["ES", "NQ", "NKD", "ZB", "ZN", "6E", "6J"]
METALS = ["GC", "SI", "HG"]
GRAINS = ["ZC", "ZW", "ZS"]
ALL = list(U.CODES)


# ------------------------------------------------------------------ rules
# Each returns every date in [a, b]. Weekly rules are the reason the old
# next-occurrence design had to go: "next Wednesday" cannot express a month.
def weekly(wd):
    def gen(a, b):
        d = a + dt.timedelta(days=(wd - a.weekday() + 7) % 7)
        while d <= b:
            yield d
            d += dt.timedelta(days=7)
    return gen


def monthly_day(day):
    """Nth of the month, rolled forward off a weekend. USDA does not publish
    on a Saturday, and the old rule happily claimed it would."""
    def gen(a, b):
        y, m = a.year, a.month
        while True:
            try:
                d = dt.date(y, m, day)
            except ValueError:
                d = dt.date(y, m, 28)
            while d.weekday() > 4:
                d += dt.timedelta(days=1)
            if d > b:
                return
            if d >= a:
                yield d
            m += 1
            if m > 12:
                y, m = y + 1, 1
    return gen


def first_friday(a, b):
    y, m = a.year, a.month
    while True:
        d = dt.date(y, m, 1)
        d += dt.timedelta(days=(4 - d.weekday() + 7) % 7)
        if d > b:
            return
        if d >= a:
            yield d
        m += 1
        if m > 12:
            y, m = y + 1, 1


def last_business_day(a, b):
    y, m = a.year, a.month
    while True:
        d = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
        while d.weekday() > 4:
            d -= dt.timedelta(days=1)
        if d > b:
            return
        if d >= a:
            yield d
        m += 1
        if m > 12:
            y, m = y + 1, 1


def listed(dates):
    def gen(a, b):
        for s in dates:
            d = dt.date.fromisoformat(s)
            if a <= d <= b:
                yield d
    return gen


def seasonal(gen, months):
    """USDA Crop Progress runs April to November. Without this the old tab
    invented a January release every year."""
    def wrapped(a, b):
        for d in gen(a, b):
            if d.month in months:
                yield d
    return wrapped


# ---------------------------------------------------------------- schedule
# Hand-maintained lists. When one runs out the tab says so rather than
# quietly dropping the row — see exhausted() below.
FOMC = ["2026-09-16", "2026-10-28", "2026-12-09",
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16"]
CPI = ["2026-09-11", "2026-10-13", "2026-11-12", "2026-12-10",
       "2027-01-13", "2027-02-11", "2027-03-11"]
ECB = ["2026-09-10", "2026-10-29", "2026-12-17", "2027-02-04"]
BOJ = ["2026-09-18", "2026-10-30", "2026-12-18", "2027-01-22"]

# The releases that move the whole board rather than one contract. Colour is
# reserved for these: highlighting everything inside a week lit up the entire
# first block, which is the same as highlighting nothing. Proximity is already
# carried twice over, by the Countdown column and by the week rules.
#
# Deliberately excludes the weekly inventory and claims numbers. They matter
# to their contract, but they arrive every Wednesday and Thursday without fail,
# so marking them lights a quarter of the table and the eye stops seeing it.
# What earns colour is the irregular, scheduled, board-wide event.
HIGH = {"FOMC Rate Decision", "ECB Rate Decision", "BOJ Rate Decision",
        "CPI Inflation", "PCE Inflation", "Nonfarm Payrolls", "USDA WASDE"}

# name, type, ET time, symbols, rule, exact?
EVENTS = [
    ("FOMC Rate Decision", "Policy", "14:00",
     ["ES", "NQ", "GC", "SI", "HG", "6E", "6J", "ZB", "ZN", "BTC"],
     listed(FOMC), True),
    ("ECB Rate Decision", "Policy", "08:15", ["6E", "ES"], listed(ECB), True),
    ("BOJ Rate Decision", "Policy", "23:00", ["6J", "NKD"], listed(BOJ), True),
    ("CPI Inflation", "Macro", "08:30",
     ["ES", "NQ", "GC", "SI", "6E", "6J", "ZB", "ZN"], listed(CPI), True),
    ("PCE Inflation", "Macro", "08:30", ["ES", "NQ", "GC", "SI", "ZB", "ZN"],
     last_business_day, False),
    ("Nonfarm Payrolls", "Macro", "08:30", FIN + ["GC", "SI"],
     first_friday, True),
    ("Jobless Claims", "Macro", "08:30", ["ES", "NQ", "ZN"], weekly(3), True),
    ("EIA Petroleum Status", "Inventory", "10:30", ["CL"], weekly(2), True),
    ("EIA Nat Gas Storage", "Inventory", "10:30", ["NG"], weekly(3), True),
    ("API Crude (private)", "Inventory", "16:30", ["CL"], weekly(1), True),
    ("USDA WASDE", "Report", "12:00", GRAINS + ["SB", "KC"],
     monthly_day(12), False),
    ("USDA Crop Progress", "Report", "16:00", ["ZC", "ZS"],
     seasonal(weekly(0), range(4, 12)), False),
    ("USDA Export Sales", "Report", "08:30", GRAINS, weekly(3), True),
    ("CFTC Commitments of Traders", "Positioning", "15:30", ALL,
     weekly(4), True),
]

# ---------------------------------------------------------------- holidays
# Three calendars, not one. A full exchange closure, a SIFMA bond-market
# recommendation where CME futures keep trading but the cash Treasury market
# does not, and Singapore's own gazette. The bond dates matter because ZB and
# ZN trade through them on thin liquidity with no cash market underneath.
#
# Lunar and Islamic dates are gazetted about a year ahead and shift, so verify
# the Singapore list against MOM each December rather than trusting it on.
US_HOLIDAYS = {
    "2026-09-07": "Labor Day", "2026-11-26": "Thanksgiving",
    "2026-11-27": "Day after Thanksgiving (early close)",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day", "2027-01-18": "Martin Luther King Jr Day",
    "2027-02-15": "Presidents' Day", "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day", "2027-06-18": "Juneteenth (observed)",
    "2027-07-05": "Independence Day (observed)", "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving", "2027-11-26": "Day after Thanksgiving (early close)",
    "2027-12-24": "Christmas (observed)",
}
# SIFMA recommended closes: cash Treasuries shut, CME futures open.
US_BOND_HOLIDAYS = {
    "2026-10-12": "Columbus Day", "2026-11-11": "Veterans Day",
    "2027-10-11": "Columbus Day", "2027-11-11": "Veterans Day",
}
SG_HOLIDAYS = {
    "2026-11-08": "Deepavali", "2026-11-09": "Deepavali (observed)",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-02-06": "Chinese New Year", "2027-02-07": "Chinese New Year",
    "2027-02-08": "Chinese New Year (observed)",
    "2027-03-11": "Hari Raya Puasa",
    "2027-03-26": "Good Friday", "2027-05-01": "Labour Day",
    "2027-05-18": "Hari Raya Haji", "2027-05-20": "Vesak Day",
    "2027-08-09": "National Day",
    "2027-11-05": "Deepavali", "2027-12-25": "Christmas Day",
}


def exhausted(today=None):
    """Which hand-maintained lists have run out. A row that silently stops
    appearing is worse than a warning that it has."""
    today = today or dt.date.today()
    out = []
    for label, lst in (("FOMC", FOMC), ("CPI", CPI), ("ECB", ECB), ("BOJ", BOJ)):
        if not any(dt.date.fromisoformat(s) >= today for s in lst):
            out.append(label)
    return out


# ------------------------------------------------------------------ build
def _times(d: dt.date, hhmm: str):
    """(ET label, SGT label) for a date and an Eastern wall-clock time.

    The SGT label carries a +1 when the conversion crosses midnight. Without
    it a 16:00 ET report reads as 04:00 on the same morning, which is twelve
    hours before it happens — the single most misleading thing this tab
    could do for someone trading US sessions from Singapore.
    """
    h, m = (int(x) for x in hhmm.split(":"))
    et = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=ET)
    sg = et.astimezone(SG)
    tag = "+1" if sg.date() > d else ""
    return hhmm, sg.strftime("%H:%M") + tag


def build(days: int = 28, symbol: str = "All", today=None) -> list:
    """Every occurrence in the horizon, sorted, one row per event."""
    today = today or dt.date.today()
    end = today + dt.timedelta(days=days)
    rows = []

    for name, kind, hhmm, syms, gen, exact in EVENTS:
        if symbol != "All" and symbol not in syms:
            continue
        for d in gen(today, end):
            et, sg = _times(d, hhmm)
            rows.append({"date": d, "symbols": syms, "time_et": et,
                         "time_sg": sg, "event": name, "type": kind,
                         "high": name in HIGH, "exact": exact})

    if symbol == "All":
        for src, region, label in (
                (US_HOLIDAYS, "US", "US market closed"),
                (US_BOND_HOLIDAYS, "US-B", "US bond market closed, futures open"),
                (SG_HOLIDAYS, "SG", "Singapore public holiday")):
            for iso, nm in src.items():
                d = dt.date.fromisoformat(iso)
                if today <= d <= end:
                    rows.append({"date": d, "symbols": [], "time_et": "",
                                 "time_sg": "", "event": f"{nm} — {label}",
                                 "type": "Holiday", "region": region,
                                 "high": False, "exact": True})

    rows.sort(key=lambda r: (r["date"], r["time_et"] or "00:00"))
    for r in rows:
        n = (r["date"] - today).days
        r["days"] = n
        r["when"] = ("today" if n == 0 else "tomorrow" if n == 1
                     else f"in {n}d")
    return rows


def symbols() -> list:
    used = {s for _, _, _, syms, _, _ in EVENTS for s in syms}
    return ["All"] + [c for c in U.CODES if c in used]
