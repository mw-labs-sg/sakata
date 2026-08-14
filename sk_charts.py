"""Sakata — every SVG the site draws, ported from charts.js.

Three primitives shared by six tabs: a horizontal bar field, a multi-series
line chart, and candles with overlays. Colours come from sk_ui.C, which is
resolved from the same CSS tokens the browser reads, so a theme flip needs no
change here.

Kept hand-rolled rather than swapped for Plotly. A charting library restyled
to look like this would be more code than this, and the output would still be
subtly different at every axis and label.
"""
import math

from sk_ui import C, esc, num


def bar_chart(items, w=1100) -> str:
    """Horizontal bars with the value at the end of each. items: [{k,v,c}]."""
    row_h, pad_l, pad_r, pad_t, pad_b = 26, 104, 52, 4, 4
    h = len(items) * row_h + pad_t + pad_b
    vals = [d["v"] for d in items] + [0.0]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    lo -= span * 0.04
    hi += span * 0.04
    span = hi - lo
    iw = w - pad_l - pad_r

    def x(v):
        return pad_l + (v - lo) / span * iw

    zero = x(0)
    s = (f'<svg class="chart" viewBox="0 0 {w} {h}" '
         f'preserveAspectRatio="xMidYMid meet">')
    # Zero is the only rule that earns a line. Gridlines behind eight bars are
    # furniture: the value sits at the end of each bar instead.
    s += (f'<line x1="{zero}" y1="{pad_t}" x2="{zero}" y2="{h - pad_b}" '
          f'stroke="{C["axis"]}" stroke-width="1"/>')
    for i, d in enumerate(items):
        y = pad_t + i * row_h
        bh, col = 14, d.get("c") or C["other"]
        xv = x(d["v"])
        x0 = min(xv, zero)
        bw = max(abs(xv - zero), 2)
        s += (f'<text class="lbl" x="{pad_l - 12}" y="{y + bh / 2 + 5}" '
              f'text-anchor="end">{esc(d["k"])}</text>')
        s += (f'<rect x="{x0}" y="{y + 3}" width="{bw}" height="{bh}" rx="1.5" '
              f'fill="{col}" opacity="{".92" if d["v"] >= 0 else ".62"}"/>')
        # The value sits at the outer end of its bar — unless the bar has run
        # into the label column, in which case it parks past the zero rule.
        if d["v"] >= 0:
            tx, anchor = xv + 8, "start"
        elif x0 - 8 >= pad_l + 6:
            tx, anchor = x0 - 8, "end"
        else:
            tx, anchor = zero + 8, "start"
        sign = "+" if d["v"] >= 0 else ""
        s += (f'<text class="val" x="{tx}" y="{y + bh / 2 + 5}" '
              f'text-anchor="{anchor}">{sign}{num(d["v"], 2)}</text>')
    return s + "</svg>"


def line_chart(labels, series, bars=None, w=1100, h=280, dec=2) -> str:
    """series: [{k,v,c,w?,dash?,o?}]. bars is an optional volume/OI underlay."""
    pad_l, pad_r, pad_t, pad_b = 52, 46, 12, 42
    allv = [v for sr in series for v in sr["v"]
            if v is not None and v == v]
    if not allv:
        return '<div class="skel">no data</div>'
    lo, hi = min(allv), max(allv)
    pad = (hi - lo) * 0.14 or abs(hi) * 0.02 or 1
    lo -= pad
    hi += pad
    iw, ih, n = w - pad_l - pad_r, h - pad_t - pad_b, len(labels)

    def x(i):
        return pad_l + (iw / 2 if n == 1 else i / (n - 1) * iw)

    def y(v):
        return pad_t + ih - (v - lo) / (hi - lo) * ih

    s = (f'<svg class="chart" viewBox="0 0 {w} {h}" '
         f'preserveAspectRatio="xMidYMid meet">')
    for g in range(5):
        gy = pad_t + ih * g / 4
        s += (f'<line class="grid" x1="{pad_l}" y1="{gy}" x2="{w - pad_r}" '
              f'y2="{gy}"/>')
        s += (f'<text class="axis" x="{pad_l - 8}" y="{gy + 3}" '
              f'text-anchor="end">{num(hi - (hi - lo) * g / 4, dec)}</text>')
    if bars:
        clean = [v for v in bars if v is not None]
        bmax = max(clean) if clean else 0
        if bmax > 0:
            for i, v in enumerate(bars):
                if v is None:
                    continue
                bh = v / bmax * ih * 0.42
                s += (f'<rect x="{x(i) - 3}" y="{pad_t + ih - bh}" width="6" '
                      f'height="{bh}" fill="{C["volbar"]}" opacity=".95" rx="1"/>')
    for sr in series:
        d, started = "", False
        for i, v in enumerate(sr["v"]):
            if v is None or v != v:
                continue
            d += f'{"L" if started else "M"}{x(i):.1f} {y(v):.1f} '
            started = True
        if not d:
            continue
        dash = f' stroke-dasharray="{sr["dash"]}"' if sr.get("dash") else ""
        s += (f'<path d="{d}" fill="none" stroke="{sr["c"]}" '
              f'stroke-width="{sr.get("w", 2)}"{dash} stroke-linejoin="round" '
              f'opacity="{sr.get("o", 1)}"/>')
    every = math.ceil(n / 12) or 1
    for i, lb in enumerate(labels):
        if i % every:
            continue
        s += (f'<text class="axis" transform="translate({x(i)},{h - 12}) '
              f'rotate(-40)" text-anchor="end">{esc(lb)}</text>')
    return s + "</svg>"


def candles(t, o, hh, l, c, overlays, w=1100, h=300, dec=2) -> str:
    """Candles with named overlay lines, each labelled at its right edge."""
    pad_l, pad_r, pad_t, pad_b = 52, 12, 10, 34
    allv = list(hh) + list(l)
    for ov in overlays:
        allv += list(ov["v"])
    allv = [v for v in allv if v is not None and v == v]
    if not allv:
        return '<div class="skel">no data</div>'
    lo, hi = min(allv), max(allv)
    pad = (hi - lo) * 0.06 or 1
    lo -= pad
    hi += pad
    iw, ih, n = w - pad_l - pad_r, h - pad_t - pad_b, len(t)
    step = iw / n
    bw = max(min(step * 0.62, 9), 1.6)

    def x(i):
        return pad_l + step * (i + 0.5)

    def y(v):
        return pad_t + ih - (v - lo) / (hi - lo) * ih

    s = (f'<svg class="chart" viewBox="0 0 {w} {h}" '
         f'preserveAspectRatio="xMidYMid meet">')
    for g in range(5):
        gy = pad_t + ih * g / 4
        s += (f'<line class="grid" x1="{pad_l}" y1="{gy}" x2="{w - pad_r}" '
              f'y2="{gy}"/>')
        s += (f'<text class="axis" x="{pad_l - 8}" y="{gy + 3}" '
              f'text-anchor="end">{num(hi - (hi - lo) * g / 4, dec)}</text>')
    for i in range(n):
        if c[i] is None:
            continue
        up = c[i] >= o[i]
        col = C["up"] if up else C["down"]
        s += (f'<line x1="{x(i)}" y1="{y(hh[i])}" x2="{x(i)}" y2="{y(l[i])}" '
              f'stroke="{col}" stroke-width="1" opacity=".75"/>')
        yo, yc = y(o[i]), y(c[i])
        s += (f'<rect x="{x(i) - bw / 2}" y="{min(yo, yc)}" width="{bw}" '
              f'height="{max(abs(yc - yo), 1)}" fill="{col}" opacity=".85"/>')
    for ov in overlays:
        d, started, last = "", False, None
        for i, v in enumerate(ov["v"]):
            if v is None or v != v:
                continue
            d += f'{"L" if started else "M"}{x(i):.1f} {y(v):.1f} '
            started, last = True, v
        if not d:
            continue
        dash = f' stroke-dasharray="{ov["dash"]}"' if ov.get("dash") else ""
        s += (f'<path d="{d}" fill="none" stroke="{ov["c"]}" '
              f'stroke-width="{ov.get("w", 1.3)}"{dash} '
              f'opacity="{ov.get("o", 0.9)}"/>')
        s += (f'<text class="axis" x="{w - pad_r - 2}" y="{y(last) - 3}" '
              f'text-anchor="end" fill="{ov["c"]}">{esc(ov["k"])}</text>')
    every = math.ceil(n / 8) or 1
    for i, lb in enumerate(t):
        if i % every:
            continue
        s += (f'<text class="axis" x="{x(i)}" y="{h - 10}" '
              f'text-anchor="middle">{esc(str(lb)[5:10])}</text>')
    return s + "</svg>"
