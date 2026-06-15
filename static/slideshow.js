'use strict';
/* Injected by the template: SLIDE_SECONDS, FADE_MS, VERSION_POLL_SECONDS,
   NEXT_OFFSET, PHOTO_COUNT, TZ_MAIN, TZ_ZONES, ADAPTIVE_COLOR.

   ARMv6 WebKit note: subresource loads AND fetch()/XHR spin-deadlock on this
   WebKit2GTK build (WTF lock held during response processing). Only navigation
   and iframe navigation (FrameLoader path) are safe. Dynamic img.src prohibited.
   Photos/weather/events are server-rendered; JS handles:
     1. Scale-to-fit (letterbox 1920×1080 canvas)
     2. Live clocks + date
     3. "Next" event marker
     4. Crossfade slideshow loop
     5. Lightweight photo-version poll → reload on new photos
     6. Safety-net full-page reload every 5 min
     7. Adaptive color — photo-driven CSS var theming */

const REFRESH_MS = 5 * 60 * 1000;   // safety-net reload every 5 min
const NO_PHOTO_RELOAD = 30 * 1000;  // when empty, re-check sooner

document.documentElement.style.setProperty('--fade-ms', FADE_MS + 'ms');

// ── Scale-to-fit ────────────────────────────────────────────────────────────
const kioskEl = document.querySelector('.kiosk');
function fit() {
  const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  kioskEl.style.transform = 'scale(' + s + ')';
}
fit();
window.addEventListener('resize', fit);

// ── Adaptive color engine ───────────────────────────────────────────────────
// Photos are data: URIs — same-origin, so canvas.getImageData() is not tainted.
// Downscale to ~60px before sampling to keep cost minimal on ARMv6.

function rgb2hsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  var h = 0, s = 0, l = (mx + mn) / 2;
  if (mx !== mn) {
    var d = mx - mn;
    s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    if (mx === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
  }
  return [h * 360, s, l];
}
var _cl = function(v, a, b) { return Math.min(b, Math.max(a, v)); };
var _hsl  = function(h, s, l)    { return 'hsl(' + h.toFixed(0) + ' ' + (s*100).toFixed(1) + '% ' + (l*100).toFixed(1) + '%)'; };
var _hsla = function(h, s, l, a) { return 'hsl(' + h.toFixed(0) + ' ' + (s*100).toFixed(1) + '% ' + (l*100).toFixed(1) + '% / ' + a + ')'; };
var _hueGap = function(a, b) { var d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };

function extractTheme(img) {
  var n = 60;
  var c = document.createElement('canvas'); c.width = n; c.height = n;
  var ctx = c.getContext('2d', { willReadFrequently: true });
  try { ctx.drawImage(img, 0, 0, n, n); } catch (e) { return null; }
  var data;
  try { data = ctx.getImageData(0, 0, n, n).data; } catch (e) { return null; }

  var buckets = {};
  for (var i = 0; i < data.length; i += 4) {
    var r = data[i], g = data[i+1], b = data[i+2];
    var key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
    var e = buckets[key];
    if (!e) { e = { n: 0, r: 0, g: 0, b: 0 }; buckets[key] = e; }
    e.n++; e.r += r; e.g += g; e.b += b;
  }
  var cols = Object.values(buckets).map(function(e) {
    var r = e.r / e.n, g = e.g / e.n, b = e.b / e.n;
    var hsl = rgb2hsl(r, g, b);
    return { h: hsl[0], s: hsl[1], l: hsl[2], n: e.n };
  });
  if (!cols.length) return null;

  // dominant (most frequent) — drives dark background tint
  var dominant = cols.slice().sort(function(a, b) { return b.n - a.n; })[0];

  // vibrant accent — saturated, mid-light, reasonably common
  var accent = null, best = -1;
  for (var j = 0; j < cols.length; j++) {
    var c0 = cols[j];
    var lw = 1 - Math.abs(c0.l - 0.55) * 1.5;
    var score = c0.n * Math.pow(c0.s, 1.35) * Math.max(0.04, lw);
    if (score > best) { best = score; accent = c0; }
  }
  if (!accent) accent = dominant;

  // two secondary hues, distinct from accent and each other
  var cand = cols.filter(function(c0) { return c0.s > 0.22; })
                 .sort(function(a, b) { return (b.n * b.s) - (a.n * a.s); });
  var picks = [accent];
  for (var k = 0; k < cand.length; k++) {
    if (picks.length >= 3) break;
    var ok = true;
    for (var m = 0; m < picks.length; m++) {
      if (_hueGap(picks[m].h, cand[k].h) <= 28) { ok = false; break; }
    }
    if (ok) picks.push(cand[k]);
  }
  while (picks.length < 3) {                           // analogous fallbacks
    var base = picks[picks.length - 1];
    picks.push({ h: (base.h + 42) % 360, s: _cl(base.s, 0.45, 0.85), l: 0.6 });
  }

  var vivid = function(c0, dl) {
    return _hsl(c0.h, _cl(c0.s, 0.5, 0.92), _cl((c0.l || 0.6) + (dl || 0), 0.52, 0.72));
  };
  var aH = accent.h, aS = _cl(accent.s, 0.45, 0.9);
  var aL = _cl(accent.l, 0.55, 0.7);

  return {
    accent:     _hsl(aH, aS, aL),
    accentSoft: _hsl(aH, _cl(aS - 0.08, 0.3, 0.8), 0.78),
    p2: vivid(picks[1]),
    p3: vivid(picks[2]),
    bgA: _hsl(dominant.h, _cl(dominant.s * 0.7, 0.12, 0.5), 0.105),
    bgB: _hsl(aH,         _cl(aS * 0.5, 0.1, 0.4),           0.075),
    bgC: _hsl(picks[1].h, _cl(picks[1].s * 0.5, 0.08, 0.4),  0.05),
    glowA: _hsla(aH, _cl(aS, 0.4, 0.9), 0.5, 0.18),
    glowB: _hsla(picks[1].h, _cl(picks[1].s, 0.35, 0.85), 0.5, 0.15),
    cardTint: _hsla(aH, _cl(aS, 0.3, 0.7), 0.7, 0.12),
    // alpha variants for zchip / evcount / clock glow (avoid color-mix())
    accentA13: _hsla(aH, aS, aL, 0.13),
    accentA16: _hsla(aH, aS, aL, 0.16),
    accentA18: _hsla(aH, aS, aL, 0.18),
    accentA28: _hsla(aH, aS, aL, 0.28),
    swatches: [
      _hsl(aH, aS, _cl(accent.l, 0.5, 0.68)),
      vivid(picks[1]),
      vivid(picks[2]),
      _hsl(dominant.h, _cl(dominant.s, 0.15, 0.6), _cl(dominant.l, 0.3, 0.6)),
    ],
  };
}

function applyTheme(root, t) {
  if (!t) return;
  var S = root.style;
  S.setProperty('--accent',      t.accent);
  S.setProperty('--accent-soft', t.accentSoft);
  S.setProperty('--bg-a',        t.bgA);
  S.setProperty('--bg-b',        t.bgB);
  S.setProperty('--bg-c',        t.bgC);
  S.setProperty('--glow-a',      t.glowA);
  S.setProperty('--glow-b',      t.glowB);
  S.setProperty('--card-tint',   t.cardTint);
  S.setProperty('--accent-a13',  t.accentA13);
  S.setProperty('--accent-a16',  t.accentA16);
  S.setProperty('--accent-a18',  t.accentA18);
  S.setProperty('--accent-a28',  t.accentA28);
  // per-event and per-chip accents
  root.querySelectorAll('[data-ec-i]').forEach(function(el) {
    el.style.setProperty('--ec', t.swatches[+el.dataset.ecI % t.swatches.length]);
  });
  root.querySelectorAll('[data-cc-i]').forEach(function(el) {
    el.style.setProperty('--cc', t.swatches[+el.dataset.ccI % t.swatches.length]);
  });
}

var _firstApply = true;

function themeFromVisible() {
  if (typeof ADAPTIVE_COLOR === 'undefined' || !ADAPTIVE_COLOR) return;
  var img = document.querySelector('.slide-wrap.visible .slide-layer');
  if (!img) return;
  var run = function() {
    var t = extractTheme(img);
    if (!t) return;
    if (_firstApply) {
      kioskEl.classList.add('theme-instant');
      applyTheme(kioskEl, t);
      requestAnimationFrame(function() {
        requestAnimationFrame(function() { kioskEl.classList.remove('theme-instant'); });
      });
      _firstApply = false;
    } else {
      setTimeout(function() { applyTheme(kioskEl, t); }, 480);
    }
  };
  if (img.complete && img.naturalWidth) run();
  else img.addEventListener('load', run, { once: true });
}

// ── Clocks ──────────────────────────────────────────────────────────────────
function fmtParts(tz) {
  var opts = { hour: 'numeric', minute: '2-digit', hour12: true };
  if (tz) opts.timeZone = tz;
  var s = new Intl.DateTimeFormat('en-US', opts).format(new Date());
  var m = s.match(/(.+)\s(AM|PM)/i);
  return m ? { hm: m[1], ap: m[2].toUpperCase() } : { hm: s, ap: '' };
}

function fmtDate(tz) {
  var opts = { weekday: 'long', month: 'long', day: 'numeric' };
  if (tz) opts.timeZone = tz;
  return new Intl.DateTimeFormat('en-US', opts).format(new Date());
}

function fmtFull(tz) {
  var p = fmtParts(tz);
  return p.hm + ' ' + p.ap;
}

function tickClocks() {
  document.querySelectorAll('[data-clock]').forEach(function(el) {
    var tz  = el.dataset.tz  || undefined;
    var mode = el.dataset.clock;
    var p = fmtParts(tz || (TZ_MAIN || undefined));
    if      (mode === 'HM') el.textContent = p.hm;
    else if (mode === 'AP') el.textContent = p.ap;
    else                    el.textContent = fmtFull(tz || (TZ_MAIN || undefined));
  });
  document.querySelectorAll('[data-date]').forEach(function(el) {
    el.textContent = fmtDate(el.dataset.tz || (TZ_MAIN || undefined));
  });
}

tickClocks();
setInterval(tickClocks, 10000);

// ── Next event marker ────────────────────────────────────────────────────────
function nowMins(tz) {
  var opts = { hour: '2-digit', minute: '2-digit', hour12: false };
  if (tz) opts.timeZone = tz;
  var parts = new Intl.DateTimeFormat('en-US', opts).formatToParts(new Date());
  var h = +parts.find(function(p) { return p.type === 'hour'; }).value % 24;
  var m = +parts.find(function(p) { return p.type === 'minute'; }).value;
  return h * 60 + m;
}

function markNextEvent() {
  var rows = Array.from(document.querySelectorAll('.d4-ev[data-mins]'));
  if (!rows.length) return;
  var now = nowMins(TZ_MAIN || undefined);
  var ni = rows.findIndex(function(r) { return +r.dataset.mins >= now; });
  if (ni === -1) ni = rows.length - 1;
  rows.forEach(function(r, i) {
    var isNext = i === ni;
    r.classList.toggle('is-next', isNext);
    var tag = r.querySelector('.d4-evnow');
    if (tag) tag.style.display = isNext ? '' : 'none';
  });
}

markNextEvent();
setInterval(markNextEvent, 60000);

// ── Slideshow ────────────────────────────────────────────────────────────────
var layers = Array.from(document.querySelectorAll('.slide-wrap'));
var cur = 0;

function reloadPage() { window.location.replace('/?o=' + NEXT_OFFSET); }

function nextSlide() {
  if (layers.length <= 1) return;
  var nxt = (cur + 1) % layers.length;
  layers[nxt].classList.add('visible');
  layers[cur].classList.remove('visible');
  cur = nxt;
  themeFromVisible();
}

if (layers.length === 0) {
  setTimeout(reloadPage, NO_PHOTO_RELOAD);
} else {
  // layers[0] is server-rendered .visible — apply initial theme immediately
  themeFromVisible();
  setInterval(nextSlide, SLIDE_SECONDS * 1000);
  setTimeout(reloadPage, REFRESH_MS);
}

// ── Photo version poll (iframe navigation — ARMv6 WebKit safe) ──────────────
// fetch() and XHR spin-deadlock on this WebKit2GTK build even with no-store
// (WTF lock held during network response processing). The FrameLoader path
// used by iframe navigation is separate from SubresourceLoader and avoids it.
// One persistent hidden iframe; setting iframe.src is a navigation, not a
// subresource load. Handler is a single string compare — zero DOM mutations.
(function () {
  var _ver   = null;
  var _frame = document.createElement('iframe');
  _frame.setAttribute('aria-hidden', 'true');
  _frame.style.cssText = 'position:fixed;width:0;height:0;border:0;visibility:hidden;pointer-events:none';
  document.body.appendChild(_frame);

  _frame.addEventListener('load', function () {
    try {
      var txt = (_frame.contentDocument || _frame.contentWindow.document).body.textContent;
      var d   = JSON.parse(txt);
      if (_ver === null) { _ver = d.version; return; }
      if (d.version !== _ver) { window.location.replace('/'); }
    } catch (e) {}
  });

  setInterval(function () {
    _frame.src = '/api/photos/version?t=' + Date.now();
  }, VERSION_POLL_SECONDS * 1000);
}());
