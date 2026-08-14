/* core.js — state, routing, palette, and the helpers every tab uses.

   Loaded first. Everything else registers render functions that route()
   dispatches to, so a tab is one file you can open and read end to end
   without scrolling past nine others.

   No bundler and no module system on purpose: these are plain scripts sharing
   one global scope, in the order index.html lists them. A build step to
   concatenate files is a build step to debug. */

var cache = {};

/* Data age. A number with no timestamp beside it is a number you cannot act
   on, so the header says how old the build is in plain words and turns amber
   once it is old enough to matter. */

function ageOf(generated) {
  if (!generated) return null;
  var t = Date.parse(generated.replace(" ", "T") + "Z");
  if (isNaN(t)) return null;
  return Math.max(Math.round((Date.now() - t) / 60000), 0);
}

function ageText(mins) {
  if (mins == null) return "";
  if (mins < 2) return "just now";
  if (mins < 60) return mins + "m ago";
  var h = Math.floor(mins / 60);
  if (h < 24) return h + "h ago";
  return Math.floor(h / 24) + "d ago";
}

function stampNow() {
  var el = document.getElementById("stamp");
  if (!el || !META) return;
  var mins = ageOf(META.generated);
  el.textContent = (META.generated || "") + " UTC · " + ageText(mins) +
    (META.dry ? " · DRY" : "");
  el.className = "stamp" + (mins != null && mins > 480 ? " stale" : "");
}

/* Refresh re-fetches the committed JSON, cache-busted. It cannot make the
   BUILD run — that is a GitHub Action, and a page cannot trigger one without
   carrying a token, which a public page must never do. So this answers "am I
   looking at the newest published build", and the Actions "Run workflow"
   button answers "publish a newer one". */

function refresh(btn) {
  cache = {};
  teClear();                       /* the news tab is live, so re-pull it */
  window.SK_V = String(Date.now());
  if (btn) btn.classList.add("spin");
  load("meta").then(function (m) {
    META = m;
    stampNow();
    route();
  }).catch(fail).then(function () {
    if (btn) setTimeout(function () { btn.classList.remove("spin"); }, 400);
  });
}

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
    line: cssv("--line", "#e0e5e8"),
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

/* Tab order is reading order: what happened (Board), what is being said
   about it (News), what is scheduled (Events), then the analytical tabs,
   with the standing reference last. */
var TABS = ["Board", "News", "Events", "Margins", "Technical", "Spreads",
  "Curve", "Knowledge"];

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

function route() {
  renderTabs();
  var t = S.tab;
  busy();
  /* Three tabs need no committed file: Events is pure calendar rules, Drivers
     ships inside meta, and News is fetched live from the browser. */
  if (t === "Events") return renderEvents();
  if (t === "Knowledge") return renderKnowledge();
  if (t === "News") return renderNews();
  var file = { Board: "board", Technical: "technical", Spreads: "spreads",
    Curve: "curve", Margins: "margins" }[t];
  load(file).then(function (d) {
    if (t !== S.tab) return;
    ({ Board: renderBoard, Technical: renderTech, Spreads: renderSpreads,
      Curve: renderCurve, Margins: renderMargins })[t](d);
  }).catch(fail);
}

document.addEventListener("click", function (e) {
  var rf = e.target.closest("#refresh");
  if (rf) { refresh(rf); return; }

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
    if (id === "drGroup") S.drivers.group = v;
    route(); return;
  }

  var win = e.target.closest("[data-win]");
  if (win) { e.preventDefault(); S.spreads.period = win.dataset.win; route(); return; }

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
  if (s.dataset.sel === "spWindow") S.spreads.period = s.value;
  if (s.dataset.sel === "techCode") S.tech.code = s.value;
  if (s.dataset.sel === "curveCode") S.curve.code = s.value;
  if (s.dataset.sel === "evFilter") S.events.filter = s.value;
  route();
});

var rz;

window.addEventListener("resize", function () {
  clearTimeout(rz);
  rz = setTimeout(function () {
    if (["Board", "Technical", "Curve", "Spreads"].indexOf(S.tab) >= 0) route();
  }, 220);
});

/* ------------------------------------------------------------------ boot */
/* Wallpaper retired: the contour art competed with the tables for attention,
   and on white the data reads better with nothing behind it. contours() is
   left in place in case a textured ground is ever wanted again. */
