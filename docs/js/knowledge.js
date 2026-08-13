/* knowledge.js — what actually moves each contract.

   Five drivers per instrument, hand-maintained in sk_knowledge.py, ordered by
   how often they set the tone rather than by magnitude. A standing brief to
   read the tape against, not a feed. */

function renderKnowledge() {
  var filt = S.drivers.group;
  var cards = META.universe.filter(function (u) {
    return filt === "All" || u.group === filt;
  }).map(function (u) {
    var ds = (META.knowledge || {})[u.code] || [];
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
/* ------------------------------------------------------------------- news
   Fetched live, in the browser, on every page load — no build step, no
   schedule, no committed JSON.

   The catch, and it is the whole reason this is unusual: Trading Economics
   sends no CORS header, so the page cannot request it directly. A public
   read-only proxy fetches the HTML and adds the header. That means the tab
   depends on a third party neither of us controls, and it will occasionally
   be slow or refuse. Every other tab reads committed data and is unaffected;
   this one degrades to a dash and says why. */
