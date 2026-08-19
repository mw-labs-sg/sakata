"""Sakata — the Board: last price and the calendar ladder.

Percentages are measured against the last close BEFORE each boundary, not the
first close after it, so a week that opens on a holiday still measures from
Friday rather than from Tuesday.
"""
import datetime as dt

import sk_universe as U
from sk_fmt import r as _r


def build_board(daily: dict) -> dict:
    """Last close plus Day/WTD/MTD/QTD/YTD from daily closes."""
    rows = []
    for code in U.CODES:
        df = daily.get(code)
        if df is None or df.empty:
            continue
        s = df["close"].dropna()
        if s.empty:
            continue
        pairs = [(d.date(), float(v)) for d, v in zip(s.index, s.values)]
        today, last = pairs[-1]

        def ref_before(boundary):
            r = None
            for d, v in pairs:
                if d < boundary:
                    r = v
                else:
                    break
            return r

        def pct(ref):
            return _r((last / ref - 1) * 100, 2) if ref else None

        wk = today - dt.timedelta(days=today.weekday())
        mo = today.replace(day=1)
        qt = dt.date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        yr = dt.date(today.year, 1, 1)
        rows.append({
            "code": code, "name": U.NAME[code], "sector": U.SECTOR[code],
            "group": U.GROUP_OF[U.SECTOR[code]], "dec": U.DEC[code],
            # 8, not 6. DEC goes to 7 for 6J, so rounding the display value
            # to six decimals padded the seventh with a zero that was not in
            # the data: a 0.0063355 close rendered as 0.0063360 on Board while
            # every other tab priced it correctly. The percentage columns use
            # the unrounded `last`, so this only ever affected what was shown.
            "last": _r(last, 8), "asof": str(today),
            "Day": _r((last / pairs[-2][1] - 1) * 100, 2) if len(pairs) > 1 else None,
            "WTD": pct(ref_before(wk)), "MTD": pct(ref_before(mo)),
            "QTD": pct(ref_before(qt)), "YTD": pct(ref_before(yr)),
        })
    return {"rows": rows}
