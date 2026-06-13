'use strict';

/* Injected by the template before this script:
   SLIDE_SECONDS, FADE_MS, NEXT_OFFSET, PHOTO_COUNT

   This page does NO fetch()/XHR/dynamic img.src — those deadlock the WTF
   lock in this board's WebKit build. Photos and weather are server-rendered;
   we only (a) run a live clock and (b) crossfade pre-loaded <img> via opacity,
   then reload the whole page (navigation — the reliable path) for the next
   batch + fresh weather + any newly uploaded photos. */

const CLOCK_TICK_MS    = 15 * 1000;
const NO_PHOTO_RELOAD  = 30 * 1000;        // when empty, re-check for uploads
const REFRESH_MS       = 10 * 60 * 1000;   // full reload every 10 min: advances
                                           // the photo batch + refreshes weather
                                           // (and picks up new uploads)

document.documentElement.style.setProperty('--fade-ms', FADE_MS + 'ms');

// ── Clocks (local + dual time zone) ─────────────────────────────────────────
const clockLocal   = document.getElementById('clock-local');
const clockPanama  = document.getElementById('clock-panama');
const clockDetroit = document.getElementById('clock-detroit');

function fmtZone(tz) {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', hour12: false,
    ...(tz ? { timeZone: tz } : {})
  }).format(new Date());
}

function tickClock() {
  clockLocal.textContent   = fmtZone();
  clockPanama.textContent  = fmtZone('America/Panama');
  clockDetroit.textContent = fmtZone('America/Detroit');
}

tickClock();
setInterval(tickClock, CLOCK_TICK_MS);

// ── Slideshow: loop the crossfade through this batch continuously ───────────
// A full page reload is the only reliable way to load new content on this
// ARMv6 WebKit, but reloads are heavy (the photos are inlined) and briefly
// blank the stage. So we DON'T reload to change photos — we crossfade through
// the batch on a loop, indefinitely, and reload only every REFRESH_MS to
// advance the batch + refresh weather + pick up uploads. One rare blink every
// 10 min instead of one every ~30 s.
const layers = Array.from(document.querySelectorAll('.slide-layer'));
let cur = 0;

function reloadPage() {
  window.location.replace('/?o=' + NEXT_OFFSET);
}

function nextSlide() {
  if (layers.length <= 1) return;          // nothing to crossfade
  const nxt = (cur + 1) % layers.length;   // wrap around — infinite loop
  layers[nxt].classList.add('visible');
  layers[cur].classList.remove('visible');
  cur = nxt;
}

if (layers.length === 0) {
  // No photos: periodically reload so uploads appear without a manual refresh.
  setTimeout(reloadPage, NO_PHOTO_RELOAD);
} else {
  // layers[0] is server-rendered with the .visible class already applied.
  // We deliberately do NOT use requestAnimationFrame to reveal it: rAF does
  // not fire reliably on this board (compositing is disabled), which left the
  // stage black. setInterval-driven crossfades work fine.
  setInterval(nextSlide, SLIDE_SECONDS * 1000);
  setTimeout(reloadPage, REFRESH_MS);
}
