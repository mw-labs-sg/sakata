/* board.js — last price and the Day/WTD/MTD/QTD/YTD ladder. */

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
