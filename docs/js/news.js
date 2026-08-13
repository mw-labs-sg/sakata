/* news.js — live commentary, fetched in the browser on every page load.

   Trading Economics sends no CORS header, so a public read-only proxy fetches
   the HTML and adds one. That makes this the only tab depending on a third
   party neither we nor the exchange controls; it degrades to a dash and says
   why rather than showing nothing. */

var TE_PROXIES = [
  function (u) { return "https://api.allorigins.win/raw?url=" + encodeURIComponent(u); },
  function (u) { return "https://corsproxy.io/?url=" + encodeURIComponent(u); }
];

var teCache = {};        /* in-flight promises, one per URL per page load */

var TE_TTL = 15 * 60 * 1000;   /* a commentary paragraph does not change faster */

var TE_POOL = 5;               /* concurrent proxy requests */

var TE_TIMEOUT = 14000;

/* Disk cache. The fetch is expensive — two round trips through a shared
   proxy for one to two megabytes of HTML, of which we keep one paragraph —
   so paying it again for a tab switch or a reload two minutes later is
   waste. Fifteen minutes is well inside how often the source updates. */

function teStore(url) {
  try {
    var raw = localStorage.getItem("sk-te:" + url);
    if (!raw) return null;
    var o = JSON.parse(raw);
    return (Date.now() - o.t < TE_TTL) ? o.v : null;
  } catch (e) { return null; }
}

function tePut(url, v) {
  try {
    localStorage.setItem("sk-te:" + url, JSON.stringify({ t: Date.now(), v: v }));
  } catch (e) { /* quota or private mode — the cache is optional */ }
}

function teClear() {
  teCache = {};
  try {
    Object.keys(localStorage).forEach(function (k) {
      if (k.indexOf("sk-te:") === 0) localStorage.removeItem(k);
    });
  } catch (e) {}
}

function teFetchNow(url) {
  var attempt = function (i) {
    if (i >= TE_PROXIES.length) return Promise.reject(new Error("no proxy"));
    /* Without a timeout one stalled proxy connection holds a pool slot until
       the browser gives up, which is what turns "slow" into "never". */
    var ctl = ("AbortController" in window) ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, TE_TIMEOUT);
    return fetch(TE_PROXIES[i](url),
                 { cache: "no-store", signal: ctl ? ctl.signal : undefined })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (t) { clearTimeout(timer); return t; })
      .catch(function (e) { clearTimeout(timer); return attempt(i + 1); });
  };
  return attempt(0).then(teBlurb);
}

/* A pool, not a stampede. Seventeen simultaneous requests to a free shared
   proxy get throttled or queued, so the tail arrives LATER than it would
   have with a steady five in flight. */

var teQueue = [], teActive = 0;

function tePump() {
  while (teActive < TE_POOL && teQueue.length) {
    var job = teQueue.shift();
    teActive++;
    job();
  }
}

function teFetch(url) {
  if (teCache[url]) return teCache[url];
  var hit = teStore(url);
  if (hit) {
    teCache[url] = Promise.resolve(hit);
    return teCache[url];
  }
  teCache[url] = new Promise(function (resolve) {
    teQueue.push(function () {
      teFetchNow(url).then(function (v) {
        if (v) tePut(url, v);
        resolve(v);
      }).catch(function () { resolve(null); })
        .then(function () { teActive--; tePump(); });
    });
    tePump();
  });
  return teCache[url];
}

/* The same heuristic the Python scraper used: find the first real news link,
   then walk up until an ancestor holds both the headline and a date. The
   text between them is the commentary. Structural rather than selector-based,
   so a class rename on their side does not break it. */

function teBlurb(html) {
  var doc = new DOMParser().parseFromString(html, "text/html");
  var links = doc.querySelectorAll("a[href*='/news/']"), a = null;
  for (var i = 0; i < links.length; i++) {
    if (/\/news\/\d+/.test(links[i].getAttribute("href") || "") &&
        links[i].textContent.trim()) { a = links[i]; break; }
  }
  if (!a) return null;
  var head = a.textContent.trim(), node = a;
  for (var k = 0; k < 5; k++) {
    node = node.parentElement;
    if (!node) break;
    var txt = node.textContent.replace(/\s+/g, " ").trim();
    var at = txt.indexOf(head);
    var after = at >= 0 ? txt.slice(at + head.length) : txt;
    var m = after.match(/(20\d\d-\d\d-\d\d)/);
    if (m && m.index > 40) {
      return { blurb: after.slice(0, m.index).trim(), date: m[1] };
    }
  }
  return null;
}

function renderNews() {
  var te = META.te || {};
  var codes = META.universe.filter(function (u) { return te[u.code]; });
  if (!codes.length) {
    return view('<div class="skel">No commentary sources configured.</div>');
  }

  /* Draw the shell first and fill each panel as it lands. Sixteen sequential
     fetches would take fifteen seconds and show nothing until the last one;
     in parallel the first paragraphs appear in about a second. */
  function column(group) {
    var items = codes.filter(function (u) { return u.group === group; })
      .map(function (u) {
        return '<div class="mkt" id="te-' + u.code + '"><h6>' +
          esc(u.code + "  " + (u.name || "")) + "</h6>" +
          '<p class="faint">loading…</p></div>';
      }).join("");
    if (!items) return "";
    return '<div><div class="eyebrow">' + esc(group) + "</div>" +
      '<div class="card">' + items + "</div></div>";
  }
  var groups = Object.keys(META.groups || { Financials: 1, Commodities: 1 });
  view('<div class="grid2 news">' + groups.map(column).join("") + "</div>");

  codes.forEach(function (u) {
    teFetch(te[u.code]).then(function (r) {
      var el = document.getElementById("te-" + u.code);
      if (!el) return;                       /* tab changed while in flight */
      if (!r || !r.blurb) {
        el.querySelector("p").outerHTML =
          '<p class="faint">not parsed — the source page changed shape</p>';
        return;
      }
      el.querySelector("p").outerHTML = "<p>" + esc(r.blurb) + "</p>" +
        (r.date ? '<span class="when">' + esc(r.date) + "</span>" : "");
    }).catch(function () {
      var el = document.getElementById("te-" + u.code);
      if (el) el.querySelector("p").outerHTML =
        '<p class="faint">unreachable — the CORS proxy refused</p>';
    });
  });
}

/* ----------------------------------------------------------------- route */
