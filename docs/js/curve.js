/* curve.js — term structure, roll, and annualised carry. */

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
