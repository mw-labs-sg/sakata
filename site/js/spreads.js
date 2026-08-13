/* spreads.js — the ranked field, nine windows, and the leg charts.

   Outrights and pairs are ranked in ONE pool on purpose: an outright landing
   at rank 3 is a direct statement that spreading added nothing that window. */

function digest(p) {
  var L = [];
  L.push("SAKATA · " + p.window + " · " + p.note);
  L.push("generated    " + (META.generated || "") + " UTC");
  L.push("window       " + p.window + ", " + p.start + " to " + p.end +
    " (" + p.span + " calendar days)");
  L.push("sample       " + p.bars + " bars, " + p.instruments +
    " instruments, annualised x" + p.ann);
  L.push("Sharpe SE    +/-" + p.se + " over this span");
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
  if (!d.data[per]) per = S.spreads.period = d.periods[0];
  var p = d.data[per];
  if (!p) return view('<div class="skel">No spread field was built.</div>');

  /* ---- the cross-window scan. One window's winner is an artefact until you
     know whether the neighbouring windows agree, and where the best OUTRIGHT
     landed says whether spreading earned its complexity at all. */
  var sumHead = '<th class="l">Window</th><th class="l">Top candidate</th>' +
    '<th class="l">Kind</th><th>Sharpe</th><th>± SE</th><th>ER</th>' +
    '<th>Tot%</th><th>Bars</th><th class="l">Best outright</th><th>at #</th>';
  var sumBody = (d.summary || []).map(function (r) {
    var on = r.window === per;
    return '<tr class="' + (on ? "out" : "") + '">' +
      '<td class="l"><a href="#" data-win="' + esc(r.window) + '">' +
      esc(r.window) + "</a></td>" +
      '<td class="l">' + esc(r.label || "—") + "</td>" +
      '<td class="l ' + (r.kind === "outright" ? "sh" : "lg") + '">' +
      esc(r.kind || "—") + "</td>" +
      cell(r.sharpe, 2, "last") + cell(r.se, 2, "faint") +
      cell(r.er, 3, "dim") + pct(r.tot, 1) + cell(r.bars, 0, "faint") +
      '<td class="l dim">' + esc(r.bestOut || "—") + "</td>" +
      cell(r.outRank, 0, (r.outRank && r.outRank <= 5) ? "sh" : "faint") +
      "</tr>";
  }).join("");

  /* Which candidates hold across windows. This is the answer to "which pair
     is actually optimal" — one window's winner is a fortnight of luck until
     the neighbouring windows agree with it. */
  var pers = (d.persist || []).slice(0, 8);
  var persHead = '<th class="l">Position</th><th class="l">Kind</th>' +
    '<th>Windows</th><th>Best #</th><th>Avg #</th><th>Med Sharpe</th>' +
    '<th>Med ER</th><th class="l">Appears in</th>';
  var persBody = pers.map(function (r) {
    var strong = r.count >= Math.ceil((d.nWindows || 9) / 2);
    return '<tr class="' + (strong ? "out" : "") + '">' +
      '<td class="l">' + esc(r.label) + "</td>" +
      '<td class="l ' + (r.kind === "outright" ? "sh" : "lg") + '">' +
      esc(r.kind) + "</td>" +
      '<td class="last">' + r.count + "/" + (d.nWindows || 9) + "</td>" +
      cell(r.best, 0, "dim") + cell(r.avgRank, 1, "dim") +
      cell(r.medSharpe, 2, "dim") + cell(r.medER, 3, "dim") +
      '<td class="l faint">' + esc(r.windows.join(" ")) + "</td></tr>";
  }).join("");

  var sel = '<select data-sel="spWindow">' + d.periods.map(function (w) {
    return '<option value="' + w + '"' + (w === per ? " selected" : "") + ">" +
      esc(w) + "</option>";
  }).join("") + "</select>";

  var chips = [
    p.note, p.bars + " bars · " + p.instruments + " instruments",
    "Sharpe SE ±" + p.se, p.start + " → " + p.end,
    "vol-adjusted legs", "cap " + d.cap + ":1"
  ].map(function (c) { return '<span class="chip">' + esc(c) + "</span>"; }).join("");

  var verdict = [];
  if (p.bestPair) verdict.push("best pair <b>" + esc(p.bestPair) + "</b>");
  if (p.bestOut) verdict.push("best outright <b>" + esc(p.bestOut) +
    "</b> at rank " + p.outRank);
  verdict.push("median Sharpe — pairs <b>" + p.medPair + "</b>, outrights <b>" +
    p.medOut + "</b>");
  if (p.medOut >= p.medPair) {
    verdict.push("<b>outrights win the like-for-like — spreading is not " +
      "paying on this horizon</b>");
  }

  /* On a short span the Sharpe column is not evidence, and that fact needs
     to be ON the screen — but as a flag, not a paragraph. The reasoning
     lives in the digest, which is where you go when you want the argument. */
  var warn = "";
  if (p.se > 2.5) {
    warn = '<div class="flag">Sharpe unsupportable at ' + p.span +
      " days — noise alone tops out near " + Math.round(p.noise) +
      " over " + p.nField + " candidates. Rank on ER.</div>";
  }

  var weak = p.se > 2.5;
  var head = '<th class="l">#</th><th class="l">Long</th><th class="l">Short</th>' +
    '<th class="l">Sector</th><th>Score</th><th' + (weak ? ' class="dim"' : "") +
    ">Sharpe</th><th" + (weak ? ' class="on"' : "") + ">ER</th>" +
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
      cell(r.sharpe, 2, weak ? "faint" : (r.sharpe >= 0 ? "pos" : "neg")) +
      cell(r.er, 3, erCls) + cell(r.win, 0, "dim") + pct(r.tot, 1) +
      cell(r.vol, 1, "dim") + cell(r.mdd, 1, "neg") + cell(r.corr, 2, "dim") +
      cell(r.ratio, 2, "dim") + "</tr>";
  }).join("");

  view(
    '<div class="eyebrow">Optimal by window</div>' +
    '<div class="note">Top-ranked candidate in each window on the same ' +
    'weighting. A position that holds across neighbouring windows is a ' +
    'different object from one that only wins the shortest. Click a window ' +
    'to open it.</div>' + table(sumHead, sumBody) +
    (pers.length ? '<div class="eyebrow" style="margin-top:24px">' +
      "Holds across windows</div>" +
      '<div class="note">How often each position appears in the top 10 of a ' +
      "window, ranked by count then by average rank — appearing 8th in six " +
      "windows is worth more than 1st in one. This is the closest thing here " +
      "to evidence that a relationship is structural rather than lucky.</div>" +
      table(persHead, persBody) : "") +
    '<div class="eyebrow" style="margin-top:24px">Window</div>' +
    '<div class="bar">' + sel + '</div>' +
    '<div class="chips">' + chips + "</div>" +
    '<div class="note">' + verdict.join(" · ") + "</div>" + warn +
    spreadCharts(p) + table(head, body) +
    "<details><summary>Digest — copy this into an LLM</summary>" +
    '<button class="btn" data-copy="dg">Copy digest</button>' +
    '<pre id="dg">' + esc(digest(p)) + "</pre></details>"
  );
}

/* Three lines per candidate: each leg rebased to 100, and the spread itself.
   The table cannot separate a spread that worked because both legs trended
   and the gap widened from one that worked because a leg collapsed. This
   can, at a glance, which is the whole reason it is here. */

function spreadCharts(p) {
  if (!p.charts || !p.charts.length) return "";
  var wide = width() > 820;
  var cols = wide ? 3 : 1;
  var w = Math.floor((width() - (cols - 1) * 12) / cols) - 24;
  var cards = p.charts.map(function (c) {
    var series = [];
    if (c.lg) series.push({ k: c.lgName, v: c.lg, c: C.pos, w: 1.2, o: 0.85 });
    if (c.sh) series.push({ k: c.shName, v: c.sh, c: C.neg, w: 1.2, o: 0.85 });
    series.push({ k: "spread", v: c.sp, c: C.deep, w: 2.2 });
    var legend = series.map(function (s) {
      return '<span class="key"><i class="sw" style="background:' + s.c +
        '"></i>' + esc(s.k) + "</span>";
    }).join("");
    return '<div class="plot"><div class="ctitle"><b>' + c.n + ". " +
      esc(c.label) + "</b><span>Sharpe " + c.sharpe + " · ER " + c.er +
      " · " + (c.tot >= 0 ? "+" : "") + c.tot + "%</span></div>" +
      '<div class="clegend">' + legend + "</div>" +
      lineChart(c.t, series, null, w, 150, 1) + "</div>";
  }).join("");
  return '<div class="eyebrow">Why they ranked</div>' +
    '<div class="note">Both legs rebased to 100 at the window open, with the ' +
    'vol-adjusted spread over them.</div>' +
    '<div class="cgrid">' + cards + "</div>";
}

/* ----------------------------------------------------------------- Curve */
