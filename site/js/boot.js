/* boot.js — runs last, once every other file has registered. */

var hash = (location.hash || "").replace("#", "");
if (hash === "Drivers") hash = "Knowledge";   /* old bookmarks still land */
if (TABS.indexOf(hash) >= 0) S.tab = hash;
load("meta").then(function (m) {
  META = m;
  stampNow();
  route();
}).catch(function (e) {
  document.getElementById("stamp").textContent = "no data";
  fail(e);
});
