/* Sakata — static futures terminal. Vanilla JS, no build step, no framework.
   The page is a viewer over JSON committed by the GitHub Action. Nothing here
   fetches a market data source directly: browsers get blocked, runners do not. */
(function () {
"use strict";

/* ------------------------------------------------------------ background */
/* Contour curves, drawn once and installed as a CSS custom property. Kept in
   JS rather than a file so there is one less asset to serve. */
function contours() {
  var top = "M-160 300C140 168 384 432 700 300S1180 120 1600 246";
  var mid = "M-160 470C220 400 420 560 780 470S1220 380 1600 452";
  var bot = "M-160 626C200 520 300 764 680 660S1150 516 1600 608";
  function band(d, n, step, op0, dop, w) {
    var s = "";
    for (var i = 0; i < n; i++) {
      var op = Math.max(op0 - i * dop, 0.015);
      s += '<path d="' + d + '" transform="translate(0 ' + (i * step) + ')" ' +
           'stroke-width="' + w + '" opacity="' + op.toFixed(3) + '"/>';
    }
    return s;
  }
  var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 900" ' +
    'preserveAspectRatio="xMidYMid slice"><g fill="none" stroke="#0f766e" ' +
    'stroke-linecap="round">' +
    band(top, 11, 27, 0.135, 0.010, 1.1) +
    band(mid, 5, 34, 0.055, 0.008, 0.9) +
    band(bot, 9, 31, 0.115, 0.011, 1.1) +
    '<path d="' + top + '" stroke="#0d9488" stroke-width="1.9" opacity="0.20"/>' +
    '<path d="' + bot + '" stroke="#0d9488" stroke-width="1.7" opacity="0.17"/>' +
    '</g></svg>';
  document.documentElement.style.setProperty(
    "--contours", 'url("data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg) + '")');
}

/* ----------------------------------------------------------------- utils */
var cache = {};
function load(name) {
  if (cache[name]) return cache[name];
  cache[name] = fetch("data/" + name + ".json?v=" + (window.SK_V || ""))
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .catch(function (e) { cache[name] = null; throw e; });
  return cache[name];
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}
function num(v, d) {
  if (v == null || isNaN(v)) return null;
  return Number(v).toLocaleString("en-US",
    { minimumFractionDigits: d, maximumFractionDigits: d });
}
function pct(v, d) {
  if (v == null || isNaN(v)) return '<td class="faint">—</td>';
  var s = (v >= 0 ? "+" : "") + num(v, d == null ? 2 : d);
  return '<td class="' + (v >= 0 ? "pos" : "neg") + '">' + s + "</td>";
}
function cell(v, d, cls) {
  if (v == null || isNaN(v)) return '<td class="faint">—</td>';
  return '<td class="' + (cls || "") + '">' + num(v, d == null ? 2 : d) + "</td>";
}
function seg(id, opts, cur) {
  return '<div class="seg" data-seg="' + id + '">' + opts.map(function (o) {
    return '<button data-v="' + esc(o) + '"' + (o === cur ? ' class="on"' : "") +
      ">" + esc(o) + "</button>";
  }).join("") + "</div>";
}
function table(head, body, cls) {
  return '<div class="card scroll"><table><thead><tr>' + head +
    "</tr></thead><tbody>" + body + "</tbody></table></div>" + (cls || "");
}

/* --------------------------------------------------------------- charts */
/* Hand-rolled SVG. A charting library would be 60kb for eight bars. */
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

function width() {
  var v = document.getElementById("view");
  return Math.max((v ? v.clientWidth : 900) - 2, 320);
}

/* ------------------------------------------------------------- palette */
/* Every colour the charts draw with is a CSS custom property, read back at
   render time. That is what makes the theme switch total: SVG fills cannot
   inherit a variable through a presentation attribute, so the JS has to ask
   for the resolved value — and asking means there is still exactly one place
   a colour is defined, in sakata.css. */
function cssv(name, fallback) {
  try {
    var v = getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
    return v || fallback;
  } catch (e) { return fallback; }
}

var C = {};

/* Sector palette. Cool and muted by design: these are identity tags, not
   signals, so nothing here may be confused with the red/green of a number.
   That is why no sector is allowed a saturated warm red. */
var SECTOR_COL = {};

/* One hue up, one down. Tints carry conviction so the eye reads strength
   before it reads the digit. */
var BIAS_COL = {};

function palette() {
  C = {
    pos: cssv("--pos", "#0a7c66"), neg: cssv("--neg", "#c2453b"),
    up: cssv("--up", "#0d9488"), down: cssv("--down", "#cf5a54"),
    teal: cssv("--teal", "#0d8f83"), deep: cssv("--teal-d", "#0d5f58"),
    amber: cssv("--amber", "#96701c"), mute: cssv("--mute", "#66727b"),
    faint: cssv("--faint", "#97a2ab"), axis: cssv("--axis", "#d3dade"),
    volbar: cssv("--volbar", "#e9edf1"), other: cssv("--sec-other", "#9aa2ab")
  };
  SECTOR_COL = {
    "Indices": cssv("--sec-indices", "#3b6ea5"),
    "Bonds": cssv("--sec-bonds", "#5c7d99"),
    "Currencies": cssv("--sec-currencies", "#7a6ba8"),
    "Crypto": cssv("--sec-crypto", "#4c8f86"),
    "Energy": cssv("--sec-energy", "#8c5a3c"),
    "Metals": cssv("--sec-metals", "#a8894f"),
    "Grains": cssv("--sec-grains", "#7d8f4e"),
    "Softs": cssv("--sec-softs", "#4f8f7d")
  };
  BIAS_COL = {
    "3": cssv("--bias3", "#0d5f58"), "2": cssv("--bias2", "#0d9488"),
    "1": cssv("--bias1", "#5fbcb1"), "0": cssv("--bias0", "#9aa4ad"),
    "-1": cssv("--biasn1", "#dda29e"), "-2": cssv("--biasn2", "#cf5a54"),
    "-3": cssv("--biasn3", "#a33f3a")
  };
}
palette();

function swatch(sec) {
  return '<i class="sw" style="background:' + (SECTOR_COL[sec] || C.other) + '"></i>';
}

/* ------------------------------------------------------------------ theme */
function setTheme(t, remember) {
  var root = document.documentElement;
  root.setAttribute("data-theme", t);
  if (remember) {
    root.setAttribute("data-theme-src", "stored");
    try { localStorage.setItem("sk-theme", t); } catch (e) {}
  }
  var m = document.querySelector('meta[name="theme-color"]');
  if (m) m.setAttribute("content", cssv("--bg", "#ffffff"));
  palette();
}
setTheme(document.documentElement.getAttribute("data-theme") || "light", false);

/* No OS listener. Dark is the product's default, not a guess at the room. */

/* ------------------------------------------------------------- app state */
var S = {
  tab: "Board",
  board: { hz: "Day" },
  tech: { hz: "Day", code: null },
  spreads: { period: "MTD" },
  curve: { code: null },
  margins: { sort: "margVol" },
  drivers: { group: "All" },
  events: { filter: "All" }
};
var HZ = ["Day", "WTD", "MTD", "QTD", "YTD"];
var TABS = ["Board", "Technical", "Spreads", "Curve", "Margins", "Drivers",
  "Events", "News"];
var META = null;

/* ------------------------------------------------------------------ tabs */
function renderTabs() {
  document.getElementById("tabs").innerHTML = TABS.map(function (t) {
    return '<button class="tab' + (t === S.tab ? " on" : "") + '" data-tab="' +
      t + '">' + t + "</button>";
  }).join("");
}

function view(html) { document.getElementById("view").innerHTML = html; }
function busy() { view('<div class="skel">Loading…</div>'); }
function fail(e) {
  view('<div class="skel">Could not load this tab — ' + esc(String(e).slice(0, 80)) +
    '.<br>If the build has never run, the JSON is not there yet.</div>');
}

/* ----------------------------------------------------------------- Board */
function renderBoard(d) {
  var hz = S.board.hz;
  var bySec = {};
  d.rows.forEach(function (r) { (bySec[r.sector] = bySec[r.sector] || []).push(r); });
  var secs = Object.keys(bySec);
  var agg = secs.map(function (s) {
    var vs = bySec[s].map(function (r) { return r[hz]; })
      .filter(function (v) { return v != null; });
    return {
      k: s, c: SECTOR_COL[s],
      v: vs.length ? vs.reduce(function (a, b) { return a + b; }, 0) / vs.length : 0
    };
  }).sort(function (a, b) { return b.v - a.v; });

  function panel(group) {
    var body = "", legend = "";
    (META.groups[group] || []).forEach(function (sec) {
      var rows = bySec[sec];
      if (!rows) return;
      legend += '<span class="key">' + swatch(sec) + esc(sec) + "</span>";
      rows.forEach(function (r) {
        body += '<tr><td class="l">' + swatch(sec) + esc(r.code) +
          ' <span class="nm">' + esc(r.name) + "</span></td>" +
          '<td class="last">' + (r.last == null ? "—" : num(r.last, r.dec)) + "</td>" +
          HZ.map(function (h) {
            var v = r[h];
            var cls = (v == null || isNaN(v)) ? "faint" : (v >= 0 ? "pos" : "neg");
            if (h === hz) cls += " on";
            return '<td class="' + cls + '">' +
              (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "") + num(v, 2)) +
              "</td>";
          }).join("") + "</tr>";
      });
    });
    var head = '<th class="l">Instrument</th><th>Last</th>' +
      HZ.map(function (h) {
        return '<th' + (h === hz ? ' class="on"' : "") + ">" + h + "</th>";
      }).join("");
    return '<div><div class="eyebrow">' + group +
      '<span class="legend">' + legend + "</span></div>" +
      table(head, body) + "</div>";
  }

  view(
    '<div class="bar">' + seg("boardHz", HZ, hz) +
    '<span class="spacer"></span><span class="chip">' + d.rows.length +
    " instruments</span></div>" +
    '<div class="eyebrow">Sector performance · ' + hz + " %</div>" +
    '<div class="plot">' + barChart(agg, width() - 22) + "</div>" +
    '<div class="grid2" style="margin-top:16px">' +
    panel("Financials") + panel("Commodities") + "</div>"
  );
}

/* ------------------------------------------------------------- Technical */
function renderTech(d) {
  var order = d.order, grid = d.grid;
  var codes = Object.keys(grid);
  if (!S.tech.code || !grid[S.tech.code]) S.tech.code = codes[0];

  /* matrix: every instrument against the full ladder, one glance */
  var head = '<th class="l">Instrument</th>' +
    order.map(function (h) { return "<th>" + h + "</th>"; }).join("") +
    "<th>Σ</th>";
  var body = "";
  var lastSec = null;
  META.universe.forEach(function (u) {
    var g = grid[u.code];
    if (!g) return;
    if (u.sector !== lastSec) {
      lastSec = u.sector;
      body += '<tr class="sec"><td class="l">' + esc(u.sector) + '</td><td colspan="' +
        (order.length + 1) + '"></td></tr>';
    }
    var tot = 0, cells = "";
    order.forEach(function (h) {
      var c = g[h];
      if (!c) { cells += '<td class="faint">—</td>'; return; }
      tot += c.score;
      cells += '<td style="color:' + BIAS_COL[String(c.score)] +
        ';font-weight:600" title="' + esc(c.bias + " · " + c.regime + " / " +
        c.retrace + " / " + c.trend) + '">' +
        (c.score > 0 ? "+" : "") + c.score + "</td>";
    });
    body += '<tr><td class="l ind"><a href="#" data-code="' + u.code + '">' +
      esc(u.code) + " " + esc(u.name) + "</a></td>" + cells +
      '<td style="color:' + (tot >= 0 ? C.pos : C.neg) +
      ';font-weight:600">' + (tot > 0 ? "+" : "") + tot + "</td></tr>";
  });

  /* drill-down for the selected instrument and horizon */
  var g = grid[S.tech.code] || {};
  if (!g[S.tech.hz]) S.tech.hz = Object.keys(g)[0];
  var c = g[S.tech.hz] || {};
  var dec = (META.universe.filter(function (u) { return u.code === S.tech.code; })[0] || {}).dec;
  var chart = c.t ? candles(c.t, c.o, c.h, c.l, c.c, [
    { k: "PH", v: c.ph, c: C.down, dash: "4 3" },
    { k: "PL", v: c.pl, c: C.up, dash: "4 3" },
    { k: "Mid", v: c.md, c: C.faint, dash: "2 4" },
    { k: "RB", v: c.vb, c: C.deep },
    { k: "RS", v: c.vs, c: C.amber }
  ], width() - 22, 300, dec) : '<div class="skel">no series</div>';

  var lv = [
    ["Prior high", c.high], ["RS target", c.rs], ["Mid", c.mid],
    ["RB stop", c.rb], ["Prior low", c.low], ["Close", c.close],
    ["MA100", c.ma100], ["MA200", c.ma200]
  ].map(function (p) {
    return '<tr><td class="l">' + p[0] + "</td>" + cell(p[1], dec) + "</tr>";
  }).join("");

  var sel = '<select data-sel="techCode">' + META.universe.filter(function (u) {
    return grid[u.code];
  }).map(function (u) {
    return '<option value="' + u.code + '"' +
      (u.code === S.tech.code ? " selected" : "") + ">" + esc(u.code + "  " + u.name) +
      "</option>";
  }).join("") + "</select>";

  view(
    '<div class="note">Range Levels: prior-segment high/low with the RB/RS ' +
    'retrace bands. Each horizon votes <b>range</b>, <b>retrace</b> and ' +
    '<b>trend</b>, summing to a bias between −3 and +3. Σ is the ladder total.</div>' +
    '<div class="eyebrow">Bias matrix</div>' + table(head, body) +
    '<div class="bar" style="margin-top:20px">' + sel +
    seg("techHz", order, S.tech.hz) + "</div>" +
    '<div class="note"><b>' + esc(S.tech.code) + " · " + esc(S.tech.hz) +
    "</b> — " + esc(c.bias || "—") + " (" + esc(c.regime || "—") + " / " +
    esc(c.retrace || "—") + " / " + esc(c.trend || "—") + ") · position " +
    (c.pos == null ? "—" : num(c.pos, 0) + "%") + " of prior range · R:R to band " +
    (c.rr_retrace == null ? "—" : num(c.rr_retrace, 2)) + "</div>" +
    '<div class="plot">' + chart + "</div>" +
    '<div class="eyebrow">Levels</div>' +
    table('<th class="l">Level</th><th>Price</th>', lv)
  );
}

/* --------------------------------------------------------------- Spreads */
function digest(p) {
  var L = [];
  L.push("SAKATA · " + p.period + " · " + p.barName + " bars");
  L.push("generated    " + (META.generated || "") + " UTC");
  L.push("window       " + p.period + ", " + Math.round(p.pct * 100) +
    "% elapsed (day " + p.span + " of " + p.total + "), closes " + p.ends);
  L.push("sample       " + p.bars + " bars, " + p.instruments +
    " instruments, annualised x" + p.ann);
  L.push("Sharpe SE    +/-" + p.se + " now, +/-" + p.seEnd + " at period close");
  L.push("field        " + p.nOut + " outrights + " + p.nPair + " pairs" +
    (p.nCapped ? ", " + p.nCapped + " hidden by the 5:1 leg cap" : ""));
  L.push("medians      pair Sharpe " + p.medPair + " vs outright " + p.medOut +
    "   <- like-for-like");
  L.push("noise floor  expected best-of-" + p.nField + " Sharpe from pure noise ~" +
    Math.round(p.noise) + ". Treat anything below that as unproven.");
  L.push("");
  L.push("composite = equal-weight rank on Sharpe, ER and Win%.");
  L.push("ER = Kaufman efficiency: |net move| / path length.");
  L.push("");
  L.push(pad("#", 3) + " " + pad("LONG", 6) + pad("SHORT", 6) + pad("SECTOR", 9) +
    rpad("SCORE", 7) + rpad("SHRP", 7) + rpad("ER", 7) + rpad("WIN%", 6) +
    rpad("TOT%", 8) + rpad("VOL%", 7) + rpad("MDD%", 7) + rpad("CORR", 6));
  p.rows.forEach(function (r) {
    L.push(rpad(String(r.n), 3) + " " + pad(r.long || "cash", 6) +
      pad(r.short || "cash", 6) + pad(String(r.sector).slice(0, 8), 9) +
      rpad(fx(r.score, 1), 7) + rpad(fx(r.sharpe, 2), 7) + rpad(fx(r.er, 3), 7) +
      rpad(fx(r.win, 0), 6) + rpad(sfx(r.tot, 2), 8) + rpad(fx(r.vol, 1), 7) +
      rpad(fx(r.mdd, 2), 7) + rpad(fx(r.corr, 2), 6));
  });
  L.push("");
  L.push("leg concentration in the top 20 — one ticker dominating the short");
  L.push("column means the field is one macro bet replicated");
  L.push("  short: " + p.legShort.map(function (a) { return a[0] + "x" + a[1]; }).join("  "));
  L.push("  long:  " + p.legLong.map(function (a) { return a[0] + "x" + a[1]; }).join("  "));
  if (p.dropped && p.dropped.length) {
    L.push("");
    L.push("dropped for thin coverage: " + p.dropped.join(", "));
  }
  return L.join("\n");
  function pad(s, n) { s = String(s); while (s.length < n) s += " "; return s; }
  function rpad(s, n) { s = String(s); while (s.length < n) s = " " + s; return s; }
  function fx(v, d) { return v == null ? "-" : Number(v).toFixed(d); }
  function sfx(v, d) { return v == null ? "-" : (v >= 0 ? "+" : "") + Number(v).toFixed(d); }
}

function renderSpreads(d) {
  var per = S.spreads.period;
  if (!d.data[per]) per = S.spreads.period = d.periods.filter(function (p) {
    return d.data[p];
  })[0];
  var p = d.data[per];
  if (!p) return view('<div class="skel">No spread field was built.</div>');

  var chips = [
    per + " · " + p.barName + " bars",
    p.bars + " bars · " + p.instruments + " instruments",
    "Sharpe SE ±" + p.se + " → ±" + p.seEnd + " at close",
    Math.round(p.pct * 100) + "% elapsed · closes " + p.ends,
    "vol-adjusted legs", "cap " + d.cap + ":1"
  ].map(function (c) { return '<span class="chip">' + esc(c) + "</span>"; }).join("");

  var verdict = [];
  if (p.bestOut) verdict.push("best outright <b>" + esc(p.bestOut) + "</b>");
  if (p.bestPair) verdict.push("best pair <b>" + esc(p.bestPair) + "</b>");
  verdict.push("median Sharpe — pairs <b>" + p.medPair + "</b>, outrights <b>" +
    p.medOut + "</b>");
  if (p.medOut >= p.medPair) {
    verdict.push("<b>outrights win the like-for-like — spreading is not paying " +
      "on this horizon</b>");
  }

  var warn = "";
  if (p.se > 2.5) {
    warn = '<div class="warn"><b>At ' + p.span + " calendar days the Sharpe " +
      "standard error is ±" + p.se + "</b>, so the composite is not supportable " +
      "here — a Sharpe of 6 is barely two SE from zero. Read the ER column " +
      "instead: it describes what the window did rather than estimating a " +
      "forward parameter. Bar size cannot help, because SE depends only on " +
      "calendar span. Expected best-of-" + p.nField + " Sharpe from pure noise " +
      "is ~" + Math.round(p.noise) + ".</div>";
  }

  var head = '<th class="l">#</th><th class="l">Long</th><th class="l">Short</th>' +
    '<th class="l">Sector</th><th>Score</th><th>Sharpe</th><th>ER</th>' +
    "<th>Win%</th><th>Tot%</th><th>Vol%</th><th>MDD%</th><th>Corr</th><th>Ratio</th>";
  var body = p.rows.map(function (r) {
    var lg = r.long ? '<span class="lg">' + esc(r.long) + "</span>"
      : '<span class="cash">cash</span>';
    var sh = r.short ? '<span class="sh">' + esc(r.short) + "</span>"
      : '<span class="cash">cash</span>';
    var erCls = r.er >= 0.30 ? "pos" : (r.er >= 0.12 ? "dim" : "faint");
    return '<tr class="' + (r.kind === "outright" ? "out" : "") + '">' +
      '<td class="l faint">' + r.n + '</td><td class="l">' + lg +
      '</td><td class="l">' + sh + '</td><td class="l faint">' + esc(r.sector) +
      "</td>" + cell(r.score, 1, "dim") +
      cell(r.sharpe, 2, r.sharpe >= 0 ? "pos" : "neg") +
      cell(r.er, 3, erCls) + cell(r.win, 0, "dim") + pct(r.tot, 1) +
      cell(r.vol, 1, "dim") + cell(r.mdd, 1, "neg") + cell(r.corr, 2, "dim") +
      cell(r.ratio, 2, "dim") + "</tr>";
  }).join("");

  view(
    '<div class="bar">' + seg("spPeriod", d.periods.filter(function (x) {
      return d.data[x];
    }), per) + "</div>" +
    '<div class="chips">' + chips + "</div>" +
    '<div class="note">' + verdict.join(" · ") + "</div>" + warn +
    table(head, body) +
    "<details><summary>Digest — copy this into an LLM</summary>" +
    '<button class="btn" data-copy="dg">Copy digest</button>' +
    '<pre id="dg">' + esc(digest(p)) + "</pre></details>"
  );
}

/* ----------------------------------------------------------------- Curve */
function renderCurve(d) {
  var codes = Object.keys(d.curves);
  if (!codes.length) {
    return view('<div class="skel">No settlement data in the last build — CME ' +
      "may have refused the runner. It usually returns on the next run.</div>");
  }
  if (!S.curve.code || !d.curves[S.curve.code]) S.curve.code = codes[0];
  var scan = codes.map(function (c) { return d.curves[c]; })
    .sort(function (a, b) { return (b.carryAnn || -99) - (a.carryAnn || -99); });

  var head = '<th class="l">Symbol</th><th class="l">Sector</th><th>Front</th>' +
    '<th>Back</th><th class="l">Shape</th><th>Roll %</th><th>Carry ann %</th>';
  var body = scan.map(function (r) {
    return '<tr><td class="l"><a href="#" data-curve="' + r.code + '">' +
      esc(r.code) + '</a></td><td class="l faint">' + esc(r.sector) + "</td>" +
      cell(r.front, 2, "dim") + cell(r.back, 2, "dim") +
      '<td class="l ' + (r.shape === "Backwardation" ? "pos" : "neg") + '">' +
      esc(r.shape) + "</td>" + pct(r.rollPct, 2) + pct(r.carryAnn, 1) + "</tr>";
  }).join("");

  var c = d.curves[S.curve.code];
  var months = c.rows.map(function (r) { return r.month; });
  var settle = c.rows.map(function (r) { return r.settle; });
  var oi = c.rows.map(function (r) {
    var v = parseFloat(String(r.oi).replace(/,/g, ""));
    return isNaN(v) ? null : v;
  });
  var arrow = c.shape === "Backwardation" ? "↘" : c.shape === "Contango" ? "↗" : "→";

  var detail = c.rows.map(function (r) {
    return '<tr><td class="l">' + esc(r.month) + "</td>" + cell(r.settle, 2) +
      '<td class="dim">' + esc(r.chg || "—") + '</td><td class="dim">' +
      esc(r.vol || "—") + '</td><td class="dim">' + esc(r.oi || "—") + "</td></tr>";
  }).join("");

  view(
    '<div class="note">Term structure from CME settlements' +
    (d.tradeDate ? " · trade date " + esc(d.tradeDate) : "") +
    ". Positive carry is backwardation — a roll tailwind for longs; negative " +
    "is contango, a roll drag.</div>" +
    '<div class="eyebrow">Carry scanner — most backwardated first</div>' +
    table(head, body) +
    '<div class="bar" style="margin-top:20px"><select data-sel="curveCode">' +
    codes.map(function (x) {
      return '<option value="' + x + '"' + (x === S.curve.code ? " selected" : "") +
        ">" + esc(x + "  " + d.curves[x].name) + "</option>";
    }).join("") + "</select></div>" +
    '<div class="note"><b>' + esc(c.code) + "</b> · " + esc(c.frontMonth) + " <b>" +
    num(c.front, 2) + "</b> → " + esc(c.backMonth) + " <b>" + num(c.back, 2) +
    "</b> · " + esc(c.shape) + " " + arrow + " · current roll " +
    (c.rollPct >= 0 ? "+" : "") + num(c.rollPct, 2) + "% · carry ann " +
    (c.carryAnn >= 0 ? "+" : "") + num(c.carryAnn, 1) + "%</div>" +
    '<div class="plot">' +
    lineChart(months, [{ k: "Settle", v: settle, c: C.teal, w: 2.4 }], oi,
      width() - 22, 280, 2) + "</div>" +
    '<div class="eyebrow">Settlements</div>' +
    table('<th class="l">Month</th><th>Settle</th><th>Change</th><th>Volume</th>' +
      "<th>OI</th>", detail)
  );
}

/* --------------------------------------------------------------- Margins */
function renderMargins(d) {
  var rows = d.rows.slice().sort(function (a, b) {
    var x = a[S.margins.sort], y = b[S.margins.sort];
    if (x == null) return 1;
    if (y == null) return -1;
    return x - y;
  });
  var head = '<th class="l">Instrument</th><th class="l">Sector</th>' +
    "<th>Maint $</th><th>Notional $</th><th>Margin %</th><th>Ann vol %</th>" +
    "<th>Marg/Vol</th><th>Days ATR</th>";
  var body = rows.map(function (r) {
    return '<tr><td class="l">' + esc(r.code) + " " + esc(r.name) +
      '</td><td class="l faint">' + esc(r.sector) + "</td>" +
      cell(r.maint, 0) + cell(r.notional, 0, "dim") + cell(r.marginPct, 2) +
      cell(r.annVol, 1, "dim") + cell(r.margVol, 2) + cell(r.daysATR, 1, "dim") +
      "</tr>";
  }).join("");
  view(
    '<div class="note">Overnight <b>maintenance</b> per contract from AMP ' +
    "(retail, roughly 10% above raw CME; BTC and ETH come from CME's own file). " +
    "<b>Marg/Vol</b> is margin % ÷ 20-day annualised vol; <b>Days ATR</b> is " +
    "margin ÷ daily dollar range. Lowest Marg/Vol first — thinnest cushion " +
    "against risk, and the first candidates for a margin hike.</div>" +
    table(head, body)
  );
}

/* ---------------------------------------------------------------- Events */
/* Pure date rules, evaluated in the browser. Deliberately not precomputed:
   these roll on the calendar, so a stale build would show stale dates. */
function nextWeekday(wd) {
  var t = new Date(); t.setHours(0, 0, 0, 0);
  var d = new Date(t);
  d.setDate(t.getDate() + ((wd - ((t.getDay() + 6) % 7)) + 7) % 7);
  return d;
}
function firstFriday(y, m) {
  var d = new Date(y, m, 1);
  d.setDate(1 + ((5 - d.getDay()) + 7) % 7);
  return d;
}
function nextFirstFriday() {
  var t = new Date(); t.setHours(0, 0, 0, 0);
  var f = firstFriday(t.getFullYear(), t.getMonth());
  if (f < t) f = firstFriday(t.getFullYear(), t.getMonth() + 1);
  return f;
}
function lastBusinessDay() {
  var t = new Date();
  var d = new Date(t.getFullYear(), t.getMonth() + 1, 0);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
  if (d < new Date(t.getFullYear(), t.getMonth(), t.getDate())) {
    d = new Date(t.getFullYear(), t.getMonth() + 2, 0);
    while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
  }
  return d;
}
function nextMonthDay(day) {
  var t = new Date(); t.setHours(0, 0, 0, 0);
  var d = new Date(t.getFullYear(), t.getMonth(), day);
  if (d < t) d = new Date(t.getFullYear(), t.getMonth() + 1, day);
  return d;
}
function nextFrom(list) {
  var t = new Date(); t.setHours(0, 0, 0, 0);
  var up = list.map(function (s) { return new Date(s + "T00:00:00"); })
    .filter(function (d) { return d >= t; });
  return up.length ? up[0] : null;
}
var FOMC = ["2026-09-16", "2026-10-28", "2026-12-09", "2027-01-27"];
var CPI = ["2026-08-12", "2026-09-11", "2026-10-13", "2026-11-12", "2026-12-10"];
var EVENTS = [
  ["EIA Petroleum Status", function () { return nextWeekday(2); }, "10:30", "High", ["CL"], true],
  ["EIA Nat Gas Storage", function () { return nextWeekday(3); }, "10:30", "High", ["NG"], true],
  ["API Crude (private)", function () { return nextWeekday(1); }, "16:30", "Med", ["CL"], true],
  ["Nonfarm Payrolls", nextFirstFriday, "08:30", "High", ["ES", "NQ", "NKD", "GC", "SI", "6E", "6J"], true],
  ["Jobless Claims", function () { return nextWeekday(3); }, "08:30", "Med", ["ES", "NQ"], true],
  ["FOMC Rate Decision", function () { return nextFrom(FOMC); }, "14:00", "High", ["ES", "NQ", "GC", "SI", "HG", "6E", "6J"], true],
  ["CPI Inflation", function () { return nextFrom(CPI); }, "08:30", "High", ["ES", "NQ", "GC", "SI", "6E", "6J"], true],
  ["PCE Inflation", lastBusinessDay, "08:30", "High", ["ES", "NQ", "GC", "SI"], false],
  ["USDA WASDE", function () { return nextMonthDay(12); }, "12:00", "High", ["ZC", "ZS", "ZW"], false],
  ["USDA Crop Progress", function () { return nextWeekday(0); }, "16:00", "Med", ["ZC", "ZS"], false],
  ["USDA Export Sales", function () { return nextWeekday(3); }, "08:30", "Med", ["ZC", "ZS", "ZW"], true]
];
function renderEvents() {
  var t = new Date(); t.setHours(0, 0, 0, 0);
  var filt = S.events.filter;
  var rows = EVENTS.map(function (e) {
    var d = null;
    try { d = e[1](); } catch (x) { d = null; }
    if (!d) return null;
    if (filt !== "All" && e[4].indexOf(filt) < 0) return null;
    var days = Math.round((d - t) / 86400000);
    return {
      d: d, when: days === 0 ? "today" : days === 1 ? "tomorrow" : "in " + days + "d",
      name: e[0], time: e[2], impact: e[3], affects: e[4].join(" "), exact: e[5]
    };
  }).filter(Boolean).sort(function (a, b) { return a.d - b.d; });

  var codes = ["All"].concat(META.universe.map(function (u) { return u.code; })
    .filter(function (c) {
      return EVENTS.some(function (e) { return e[4].indexOf(c) >= 0; });
    }));
  var head = '<th class="l">Date</th><th class="l">Time ET</th>' +
    '<th class="l">Event</th><th class="l">Impact</th><th class="l">Affects</th>' +
    '<th class="l">Countdown</th>';
  var body = rows.map(function (r) {
    var ds = r.d.toDateString().slice(0, 10);
    return '<tr><td class="l">' + (r.exact ? "" : "≈ ") + esc(ds) +
      '</td><td class="l dim">' + r.time + '</td><td class="l">' + esc(r.name) +
      '</td><td class="l ' + (r.impact === "High" ? "neg" : "dim") + '">' +
      r.impact + '</td><td class="l faint">' + esc(r.affects) +
      '</td><td class="l dim">' + r.when + "</td></tr>";
  }).join("");

  view(
    '<div class="note">Next scheduled catalyst per contract, computed in the ' +
    "browser from calendar rules — so these stay correct even if the data " +
    "build is a day stale. <b>≈</b> marks an estimate; verify before trading. " +
    "Euro and Yen also move on ECB and BOJ decisions, which are not on this " +
    "list.</div>" +
    '<div class="bar"><select data-sel="evFilter">' + codes.map(function (c) {
      return '<option' + (c === filt ? " selected" : "") + ">" + c + "</option>";
    }).join("") + "</select></div>" +
    (rows.length ? table(head, body)
      : '<div class="skel">No upcoming events for that selection.</div>')
  );
}

/* --------------------------------------------------------------- Drivers */
/* A standing frame, not a feed. These change when the structure of a market
   changes, which is why they live in the repo rather than in a scrape. */
function renderDrivers() {
  var filt = S.drivers.group;
  var cards = META.universe.filter(function (u) {
    return filt === "All" || u.group === filt;
  }).map(function (u) {
    var ds = (META.drivers || {})[u.code] || [];
    if (!ds.length) return "";
    return '<div class="dcard"><div class="dhead">' + swatch(u.sector) +
      '<b>' + esc(u.code) + "</b> " + esc(u.name) +
      '<span class="dsec">' + esc(u.sector) + "</span></div><ol class=\"dlist\">" +
      ds.map(function (x) {
        return "<li><b>" + esc(x.t) + "</b><span>" + esc(x.d) + "</span></li>";
      }).join("") + "</ol></div>";
  }).join("");

  view(
    '<div class="note">What actually moves each contract, ordered by how often ' +
    'it sets the tone rather than by how much it can move on its ' +
    'day. Maintained by hand — a driver you cannot sign is a topic, not a ' +
    'driver.</div>' +
    '<div class="bar">' + seg("drGroup", ["All", "Financials", "Commodities"], filt) +
    "</div><div class=\"dgrid\">" + cards + "</div>"
  );
}

/* ------------------------------------------------------------------ News */
function renderNews(d) {
  var mk = Object.keys(d.markets || {});
  var mkt = mk.length ? mk.map(function (c) {
    var m = d.markets[c];
    var u = META.universe.filter(function (x) { return x.code === c; })[0] || {};
    return '<div class="mkt"><h6>' + esc(c + "  " + (u.name || "")) + "</h6><p>" +
      esc(m.blurb) + "</p>" + (m.date ? '<span class="when">' + esc(m.date) +
        "</span>" : "") + "</div>";
  }).join("") : '<div class="skel">No commentary parsed in the last build.</div>';

  view(
    '<div class="note">Overnight commentary per market, scraped at build time ' +
    "from Trading Economics. One paragraph per instrument, built to copy " +
    "wholesale into an LLM.</div>" +
    '<div class="eyebrow">Market commentary</div><div class="card">' + mkt + "</div>"
  );
}

/* ----------------------------------------------------------------- route */
function route() {
  renderTabs();
  var t = S.tab;
  busy();
  if (t === "Events") return renderEvents();
  if (t === "Drivers") return renderDrivers();
  var file = { Board: "board", Technical: "technical", Spreads: "spreads",
    Curve: "curve", Margins: "margins", News: "news" }[t];
  load(file).then(function (d) {
    if (t !== S.tab) return;
    ({ Board: renderBoard, Technical: renderTech, Spreads: renderSpreads,
      Curve: renderCurve, Margins: renderMargins, News: renderNews })[t](d);
  }).catch(fail);
}

document.addEventListener("click", function (e) {
  var th = e.target.closest("#theme");
  if (th) {
    var now = document.documentElement.getAttribute("data-theme");
    setTheme(now === "dark" ? "light" : "dark", true);
    route();                       /* charts carry baked-in colours; redraw */
    return;
  }

  var tab = e.target.closest("[data-tab]");
  if (tab) { S.tab = tab.dataset.tab; location.hash = S.tab; route(); return; }

  var sg = e.target.closest("[data-seg] button");
  if (sg) {
    var id = sg.parentNode.dataset.seg, v = sg.dataset.v;
    if (id === "boardHz") S.board.hz = v;
    if (id === "techHz") S.tech.hz = v;
    if (id === "spPeriod") S.spreads.period = v;
    if (id === "drGroup") S.drivers.group = v;
    route(); return;
  }

  var code = e.target.closest("[data-code]");
  if (code) { e.preventDefault(); S.tech.code = code.dataset.code; route(); return; }

  var cv = e.target.closest("[data-curve]");
  if (cv) { e.preventDefault(); S.curve.code = cv.dataset.curve; route(); return; }

  var cp = e.target.closest("[data-copy]");
  if (cp) {
    var el = document.getElementById(cp.dataset.copy);
    if (el && navigator.clipboard) {
      navigator.clipboard.writeText(el.innerText).then(function () {
        cp.textContent = "Copied";
        setTimeout(function () { cp.textContent = "Copy digest"; }, 1600);
      });
    }
  }
});

document.addEventListener("change", function (e) {
  var s = e.target.closest("[data-sel]");
  if (!s) return;
  if (s.dataset.sel === "techCode") S.tech.code = s.value;
  if (s.dataset.sel === "curveCode") S.curve.code = s.value;
  if (s.dataset.sel === "evFilter") S.events.filter = s.value;
  route();
});

var rz;
window.addEventListener("resize", function () {
  clearTimeout(rz);
  rz = setTimeout(function () {
    if (["Board", "Technical", "Curve"].indexOf(S.tab) >= 0) route();
  }, 220);
});

/* ------------------------------------------------------------------ boot */
/* Wallpaper retired: the contour art competed with the tables for attention,
   and on white the data reads better with nothing behind it. contours() is
   left in place in case a textured ground is ever wanted again. */
var hash = (location.hash || "").replace("#", "");
if (TABS.indexOf(hash) >= 0) S.tab = hash;
load("meta").then(function (m) {
  META = m;
  document.getElementById("stamp").textContent =
    (m.generated || "") + " UTC" + (m.dry ? " · DRY" : "");
  route();
}).catch(function (e) {
  document.getElementById("stamp").textContent = "no data";
  fail(e);
});

})();
