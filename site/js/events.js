/* events.js — computed in the browser from calendar rules alone.

   Deliberately not built into JSON. Roll dates and expiries follow fixed
   rules, so computing them at page load keeps them correct even when the last
   build is days old — the one tab that cannot go stale. */

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
