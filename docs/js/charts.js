/* charts.js — every SVG the site draws.

   Three primitives, shared by six tabs: a horizontal bar field, a multi-series
   line chart, and candles with overlays. Colours come from C, which core.js
   resolves from the CSS tokens, so a theme flip needs no change here. */

function barChart(items, w, opts) {
  opts = opts || {};
  var rowH = 26, padL = 104, padR = 52, padT = 4, padB = 4;
  var h = items.length * rowH + padT + padB;
  var vals = items.map(function (d) { return d.v; });
  var lo = Math.min.apply(null, vals.concat([0]));
  var hi = Math.max.apply(null, vals.concat([0]));
  var span = (hi - lo) || 1;
  lo -= span * 0.04; hi += span * 0.04; span = hi - lo;
  var iw = w - padL - padR;
  function x(v) { return padL + (v - lo) / span * iw; }
  var zero = x(0);
  var s = '<svg class="chart" viewBox="0 0 ' + w + " " + h + '" height="' + h + '">';
  /* Zero is the only rule that earns a line. Gridlines behind eight bars are
     furniture: the value sits at the end of each bar instead. */
  s += '<line x1="' + zero + '" y1="' + padT + '" x2="' + zero + '" y2="' +
    (h - padB) + '" stroke="' + C.axis + '" stroke-width="1"/>';
  items.forEach(function (d, i) {
    var y = padT + i * rowH, bh = 14, col = d.c || C.other;
    var xv = x(d.v), x0 = Math.min(xv, zero), bw = Math.max(Math.abs(xv - zero), 2);
    s += '<text class="lbl" x="' + (padL - 12) + '" y="' + (y + bh / 2 + 5) +
      '" text-anchor="end">' + esc(d.k) + "</text>";
    s += '<rect x="' + x0 + '" y="' + (y + 3) + '" width="' + bw + '" height="' +
      bh + '" rx="1.5" fill="' + col + '" opacity="' + (d.v >= 0 ? ".92" : ".62") +
      '"/>';
    /* The value sits at the outer end of its bar — except when the bar is
       long enough that the outer end has run into the label column. Then it
       parks just past the zero rule instead, where nothing else can be. */
    var tx, anchor;
    if (d.v >= 0) { tx = xv + 8; anchor = "start"; }
    else if (x0 - 8 >= padL + 6) { tx = x0 - 8; anchor = "end"; }
    else { tx = zero + 8; anchor = "start"; }
    s += '<text class="val" x="' + tx + '" y="' + (y + bh / 2 + 5) +
      '" text-anchor="' + anchor + '">' +
      (d.v >= 0 ? "+" : "") + num(d.v, 2) + "</text>";
  });
  return s + "</svg>";
}

function lineChart(labels, series, bars, w, h, dec) {
  var padL = 52, padR = 46, padT = 12, padB = 42;
  var all = [];
  series.forEach(function (s) {
    s.v.forEach(function (v) { if (v != null && !isNaN(v)) all.push(v); });
  });
  if (!all.length) return '<div class="skel">no data</div>';
  var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
  var pad = (hi - lo) * 0.14 || Math.abs(hi) * 0.02 || 1;
  lo -= pad; hi += pad;
  var iw = w - padL - padR, ih = h - padT - padB;
  var n = labels.length;
  function x(i) { return padL + (n === 1 ? iw / 2 : i / (n - 1) * iw); }
  function y(v) { return padT + ih - (v - lo) / (hi - lo) * ih; }
  var s = '<svg class="chart" viewBox="0 0 ' + w + " " + h + '" height="' + h + '">';
  for (var g = 0; g <= 4; g++) {
    var gy = padT + ih * g / 4;
    s += '<line class="grid" x1="' + padL + '" y1="' + gy + '" x2="' + (w - padR) +
      '" y2="' + gy + '"/>';
    s += '<text class="axis" x="' + (padL - 8) + '" y="' + (gy + 3) +
      '" text-anchor="end">' + num(hi - (hi - lo) * g / 4, dec == null ? 2 : dec) +
      "</text>";
  }
  if (bars && bars.length) {
    var bmax = Math.max.apply(null, bars.filter(function (v) { return v != null; }));
    if (bmax > 0) {
      bars.forEach(function (v, i) {
        if (v == null) return;
        var bh = v / bmax * ih * 0.42;
        s += '<rect x="' + (x(i) - 3) + '" y="' + (padT + ih - bh) +
          '" width="6" height="' + bh + '" fill="' + C.volbar + '" opacity=".95" rx="1"/>';
      });
    }
  }
  series.forEach(function (sr) {
    var d = "", started = false;
    sr.v.forEach(function (v, i) {
      if (v == null || isNaN(v)) return;
      d += (started ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
      started = true;
    });
    if (!d) return;
    s += '<path d="' + d + '" fill="none" stroke="' + sr.c + '" stroke-width="' +
      (sr.w || 2) + '"' + (sr.dash ? ' stroke-dasharray="' + sr.dash + '"' : "") +
      ' stroke-linejoin="round" opacity="' + (sr.o == null ? 1 : sr.o) + '"/>';
  });
  var every = Math.ceil(n / 12);
  labels.forEach(function (lb, i) {
    if (i % every) return;
    s += '<text class="axis" transform="translate(' + x(i) + "," + (h - 12) +
      ') rotate(-40)" text-anchor="end">' + esc(lb) + "</text>";
  });
  return s + "</svg>";
}

function candles(t, o, hh, l, c, overlays, w, h, dec) {
  var padL = 52, padR = 12, padT = 10, padB = 34;
  var all = hh.concat(l);
  overlays.forEach(function (ov) { all = all.concat(ov.v); });
  all = all.filter(function (v) { return v != null && !isNaN(v); });
  if (!all.length) return '<div class="skel">no data</div>';
  var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
  var pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
  var iw = w - padL - padR, ih = h - padT - padB, n = t.length;
  var step = iw / n, bw = Math.max(Math.min(step * 0.62, 9), 1.6);
  function x(i) { return padL + step * (i + 0.5); }
  function y(v) { return padT + ih - (v - lo) / (hi - lo) * ih; }
  var s = '<svg class="chart" viewBox="0 0 ' + w + " " + h + '" height="' + h + '">';
  for (var g = 0; g <= 4; g++) {
    var gy = padT + ih * g / 4;
    s += '<line class="grid" x1="' + padL + '" y1="' + gy + '" x2="' + (w - padR) +
      '" y2="' + gy + '"/>';
    s += '<text class="axis" x="' + (padL - 8) + '" y="' + (gy + 3) +
      '" text-anchor="end">' + num(hi - (hi - lo) * g / 4, dec) + "</text>";
  }
  for (var i = 0; i < n; i++) {
    if (c[i] == null) continue;
    var up = c[i] >= o[i], col = up ? C.up : C.down;
    s += '<line x1="' + x(i) + '" y1="' + y(hh[i]) + '" x2="' + x(i) +
      '" y2="' + y(l[i]) + '" stroke="' + col + '" stroke-width="1" opacity=".75"/>';
    var yo = y(o[i]), yc = y(c[i]);
    s += '<rect x="' + (x(i) - bw / 2) + '" y="' + Math.min(yo, yc) + '" width="' +
      bw + '" height="' + Math.max(Math.abs(yc - yo), 1) + '" fill="' + col +
      '" opacity=".85"/>';
  }
  overlays.forEach(function (ov) {
    var d = "", started = false;
    ov.v.forEach(function (v, i) {
      if (v == null || isNaN(v)) return;
      d += (started ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
      started = true;
    });
    if (!d) return;
    s += '<path d="' + d + '" fill="none" stroke="' + ov.c + '" stroke-width="' +
      (ov.w || 1.3) + '"' + (ov.dash ? ' stroke-dasharray="' + ov.dash + '"' : "") +
      ' opacity="' + (ov.o == null ? 0.9 : ov.o) + '"/>';
    s += '<text class="axis" x="' + (w - padR - 2) + '" y="' +
      (y(ov.v[ov.v.length - 1]) - 3) + '" text-anchor="end" fill="' + ov.c +
      '">' + esc(ov.k) + "</text>";
  });
  var every = Math.ceil(n / 8);
  t.forEach(function (lb, i) {
    if (i % every) return;
    s += '<text class="axis" x="' + x(i) + '" y="' + (h - 10) +
      '" text-anchor="middle">' + esc(lb.slice(5, 10)) + "</text>";
  });
  return s + "</svg>";
}
