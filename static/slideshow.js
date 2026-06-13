'use strict';
/* Injected by the template: SLIDE_SECONDS, FADE_MS, NEXT_OFFSET, PHOTO_COUNT,
   TZ_MAIN, TZ_ZONES (JSON array of {label,tz}).

   Zero subresources — no fetch/XHR/dynamic img.src (ARMv6 WebKit deadlock).
   Photos, weather, and events are server-rendered. JS only handles:
     1. Scale-to-fit (letterbox 1920×1080 canvas on any screen)
     2. Live clocks + date (data-* attribute driven)
     3. "Next" event marker
     4. Crossfade slideshow loop
     5. Periodic full-page reload (fresh weather + next photo batch) */

const REFRESH_MS = 10 * 60 * 1000;  // reload every 10 min
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

// ── Clocks ──────────────────────────────────────────────────────────────────
function fmtParts(tz) {
  const opts = { hour: 'numeric', minute: '2-digit', hour12: true };
  if (tz) opts.timeZone = tz;
  const s = new Intl.DateTimeFormat('en-US', opts).format(new Date());
  const m = s.match(/(.+)\s(AM|PM)/i);
  return m ? { hm: m[1], ap: m[2].toUpperCase() } : { hm: s, ap: '' };
}

function fmtDate(tz) {
  const opts = { weekday: 'long', month: 'long', day: 'numeric' };
  if (tz) opts.timeZone = tz;
  return new Intl.DateTimeFormat('en-US', opts).format(new Date());
}

function fmtFull(tz) {
  const p = fmtParts(tz);
  return p.hm + ' ' + p.ap;
}

function tickClocks() {
  document.querySelectorAll('[data-clock]').forEach(el => {
    const tz  = el.dataset.tz  || undefined;
    const mode = el.dataset.clock;
    const p = fmtParts(tz || (TZ_MAIN || undefined));
    if      (mode === 'HM') el.textContent = p.hm;
    else if (mode === 'AP') el.textContent = p.ap;
    else                    el.textContent = fmtFull(tz || (TZ_MAIN || undefined));
  });
  document.querySelectorAll('[data-date]').forEach(el => {
    el.textContent = fmtDate(el.dataset.tz || (TZ_MAIN || undefined));
  });
}

tickClocks();
setInterval(tickClocks, 10000);

// ── Next event marker ────────────────────────────────────────────────────────
function nowMins(tz) {
  const opts = { hour: '2-digit', minute: '2-digit', hour12: false };
  if (tz) opts.timeZone = tz;
  const parts = new Intl.DateTimeFormat('en-US', opts).formatToParts(new Date());
  const h = +parts.find(p => p.type === 'hour').value % 24;
  const m = +parts.find(p => p.type === 'minute').value;
  return h * 60 + m;
}

function markNextEvent() {
  const rows = Array.from(document.querySelectorAll('.d4-ev[data-mins]'));
  if (!rows.length) return;
  const now = nowMins(TZ_MAIN || undefined);
  let ni = rows.findIndex(r => +r.dataset.mins >= now);
  if (ni === -1) ni = rows.length - 1;
  rows.forEach((r, i) => {
    const isNext = i === ni;
    r.classList.toggle('is-next', isNext);
    const tag = r.querySelector('.d4-evnow');
    if (tag) tag.style.display = isNext ? '' : 'none';
  });
}

markNextEvent();
setInterval(markNextEvent, 60000);

// ── Slideshow ────────────────────────────────────────────────────────────────
const layers = Array.from(document.querySelectorAll('.slide-layer'));
let cur = 0;

function reloadPage() { window.location.replace('/?o=' + NEXT_OFFSET); }

function nextSlide() {
  if (layers.length <= 1) return;
  const nxt = (cur + 1) % layers.length;
  layers[nxt].classList.add('visible');
  layers[cur].classList.remove('visible');
  cur = nxt;
}

if (layers.length === 0) {
  setTimeout(reloadPage, NO_PHOTO_RELOAD);
} else {
  // layers[0] is server-rendered .visible — no rAF needed (compositing off on ARMv6)
  setInterval(nextSlide, SLIDE_SECONDS * 1000);
  setTimeout(reloadPage, REFRESH_MS);
}
