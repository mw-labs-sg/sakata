/* technical.js — Range Levels across the five-rung ladder.

   Prior segment high/low, the retrace bands, bias from three independent
   votes, and the drill-down candles. */

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
