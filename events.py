"""Events tab — next scheduled catalyst per contract."""
import calendar
import datetime as _d

import pandas as pd
import streamlit as st


def _next_weekday(wd: int) -> _d.date:
    """Next date (today or later) falling on weekday wd (Mon=0 .. Sun=6)."""
    t = _d.date.today()
    return t + _d.timedelta(days=(wd - t.weekday()) % 7)


def _first_friday(y: int, m: int) -> _d.date:
    d = _d.date(y, m, 1)
    return d + _d.timedelta(days=(4 - d.weekday()) % 7)


def _next_first_friday() -> _d.date:
    t = _d.date.today()
    ff = _first_friday(t.year, t.month)
    if ff < t:
        y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
        ff = _first_friday(y, m)
    return ff


def _next_from_list(dates: list) -> _d.date | None:
    t = _d.date.today()
    upcoming = [d for d in dates if d >= t]
    return min(upcoming) if upcoming else None


def _last_business_day(y: int, m: int) -> _d.date:
    last = calendar.monthrange(y, m)[1]
    d = _d.date(y, m, last)
    while d.weekday() > 4:
        d -= _d.timedelta(days=1)
    return d


def _next_month_day(day: int) -> _d.date:
    """Next occurrence of the given day-of-month (today or future)."""
    t = _d.date.today()
    cand = _d.date(t.year, t.month, min(day, calendar.monthrange(t.year, t.month)[1]))
    if cand < t:
        y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
        cand = _d.date(y, m, min(day, calendar.monthrange(y, m)[1]))
    return cand


# Confirmed 2026 fixed dates
FOMC_2026 = [_d.date(2026, 7, 29), _d.date(2026, 9, 16),
             _d.date(2026, 10, 28), _d.date(2026, 12, 9)]
CPI_2026 = [_d.date(2026, 8, 12), _d.date(2026, 9, 11),   # confirmed
            _d.date(2026, 10, 13), _d.date(2026, 11, 12), _d.date(2026, 12, 10)]  # ≈

# name, next-date callable, time (ET), impact, affected instruments, exact?
EVENTS = [
    ("EIA Petroleum Status", lambda: _next_weekday(2), "10:30", "High", ["CL"], True),
    ("EIA Nat Gas Storage",  lambda: _next_weekday(3), "10:30", "High", ["NG"], True),
    ("API Crude (private)",  lambda: _next_weekday(1), "16:30", "Med",  ["CL"], True),
    ("Nonfarm Payrolls",     _next_first_friday,       "08:30", "High", ["ES", "NQ", "GC", "SI", "6E", "6J"], True),
    ("Jobless Claims",       lambda: _next_weekday(3), "08:30", "Med",  ["ES", "NQ"], True),
    ("FOMC Rate Decision",   lambda: _next_from_list(FOMC_2026), "14:00", "High", ["ES", "NQ", "GC", "SI", "HG", "6E", "6J"], True),
    ("CPI Inflation",        lambda: _next_from_list(CPI_2026),  "08:30", "High", ["ES", "NQ", "GC", "SI", "6E", "6J"], True),
    ("PCE Inflation",        lambda: _last_business_day(_d.date.today().year, _d.date.today().month), "08:30", "High", ["ES", "NQ", "GC", "SI"], False),
    ("USDA WASDE",           lambda: _next_month_day(12), "12:00", "High", ["ZC", "ZS"], False),
    ("USDA Crop Progress",   lambda: _next_weekday(0), "16:00", "Med",  ["ZC", "ZS"], False),
    ("USDA Export Sales",    lambda: _next_weekday(3), "08:30", "Med",  ["ZC", "ZS"], True),
]

INSTRUMENTS = ["ES", "NQ", "GC", "SI", "HG", "CL", "NG", "ZC", "ZS", "6E", "6J"]


def build_events(selected: list) -> pd.DataFrame:
    t = _d.date.today()
    rows = []
    for name, fn, time_et, impact, insts, exact in EVENTS:
        if selected and not (set(insts) & set(selected)):
            continue
        try:
            d = fn()
        except Exception:  # noqa: BLE001
            d = None
        if d is None:
            continue
        days = (d - t).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days}d"
        rows.append({
            "_sort": d,
            "Date": ("≈ " if not exact else "") + d.strftime("%a %d %b"),
            "Time ET": time_et,
            "Event": name,
            "Impact": impact,
            "Affects": " ".join(insts),
            "Countdown": when,
        })
    df = pd.DataFrame(rows).sort_values("_sort")
    return df.drop(columns="_sort") if not df.empty else df


def render_events() -> None:
    st.caption(
        "Next scheduled catalyst per contract. ✓ dates are rule-based or "
        "confirmed (auto-rolling); **≈** dates are estimates — verify before "
        "trading. Euro/Yen also move on ECB/BOJ decisions (check their calendars)."
    )
    sel = st.multiselect("Filter by instrument", INSTRUMENTS, default=[])
    df = build_events(sel)
    if df.empty:
        st.info("No upcoming events for that selection.")
    else:
        st.table(df.style.hide(axis="index"))
