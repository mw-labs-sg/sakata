/* margins.js — margin against notional, vol, and daily range. */

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
