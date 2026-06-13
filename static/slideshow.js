'use strict';

/* Injected by the template before this script:
   SLIDE_SECONDS, FADE_MS, NEXT_OFFSET, PHOTO_COUNT

   This page does NO fetch()/XHR/dynamic img.src — those deadlock the WTF
   lock in this board's WebKit build. Photos and weather are server-rendered;
   we only (a) run a live clock and (b) crossfade pre-loaded <img> via opacity,
   then reload the whole page (navigation — the reliable path) for the next
   batch + fresh weather + any newly uploaded photos. */

const CLOCK_TICK_MS    = 15 * 1000;
const NO_PHOTO_RELOAD  = 30 * 1000;   // when empty, re-check for uploads

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

// ── Slideshow: crossfade pre-rendered layers, then reload ───────────────────
const layers = Array.from(document.querySelectorAll('.slide-layer'));
let cur = 0;

function reloadBatch() {
  // Navigation load (reliable). Brings the next batch + fresh weather +
  // any newly uploaded/removed photos.
  window.location.replace('/?o=' + NEXT_OFFSET);
}

function nextSlide() {
  // After the last image in this batch has shown, reload for the next batch.
  if (cur >= layers.length - 1) {
    reloadBatch();
    return;
  }
  const nxt = cur + 1;
  layers[nxt].classList.add('visible');
  layers[cur].classList.remove('visible');
  cur = nxt;
  setTimeout(nextSlide, SLIDE_SECONDS * 1000);
}

if (layers.length === 0) {
  // No photos: periodically reload so uploads appear without a manual refresh.
  setTimeout(reloadBatch, NO_PHOTO_RELOAD);
} else {
  // Fade the first image in (also masks the reload flash), then start cycling.
  requestAnimationFrame(() => layers[0].classList.add('visible'));
  setTimeout(nextSlide, SLIDE_SECONDS * 1000);
}
