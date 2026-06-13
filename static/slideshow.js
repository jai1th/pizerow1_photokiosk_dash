'use strict';

// SLIDE_SECONDS and FADE_MS are injected by the template before this script.

const MANIFEST_POLL_MS = 60 * 1000;
const WEATHER_POLL_MS  = 15 * 60 * 1000;
const CLOCK_TICK_MS    = 15 * 1000;

// Apply fade duration from injected config
document.documentElement.style.setProperty('--fade-ms', FADE_MS + 'ms');

const layerA     = document.getElementById('layer-a');
const layerB     = document.getElementById('layer-b');
const noPhotos   = document.getElementById('no-photos');
const uploadUrl  = document.getElementById('upload-url');
const slideshow  = document.getElementById('slideshow');

const clockLocal   = document.getElementById('clock-local');
const clockPanama  = document.getElementById('clock-panama');
const clockDetroit = document.getElementById('clock-detroit');

let photos       = [];   // current shuffled rotation
let idx          = 0;    // index of the photo currently visible
let frontLayer   = layerA;
let backLayer    = layerB;
let slideTimer   = null;
let hasPhotos    = false;

// ── Utilities ─────────────────────────────────────────────────────────────

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

async function apiFetch(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.status);
    return r.json();
  } catch { return null; }
}

// ── Clocks (local + dual time zone) ─────────────────────────────────────────

// Format the current moment as HH:MM (24 h) for an optional IANA time zone.
function fmtZone(tz) {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', hour12: false,
    ...(tz ? { timeZone: tz } : {})
  }).format(new Date());
}

function tickClock() {
  clockLocal.textContent   = fmtZone();                    // device local
  clockPanama.textContent  = fmtZone('America/Panama');
  clockDetroit.textContent = fmtZone('America/Detroit');
}

tickClock();
setInterval(tickClock, CLOCK_TICK_MS);

// ── Slideshow ──────────────────────────────────────────────────────────────

function photoSrc(filename) { return '/photos/' + filename; }

function scheduleSlide() {
  clearTimeout(slideTimer);
  slideTimer = setTimeout(advance, SLIDE_SECONDS * 1000);
}

function preloadBack(filename) {
  if (filename) backLayer.src = photoSrc(filename);
}

function advance() {
  if (photos.length === 0) return;
  if (photos.length === 1) { scheduleSlide(); return; }

  const nextIdx      = (idx + 1) % photos.length;
  const nextFilename = photos[nextIdx];
  const preloadIdx   = (nextIdx + 1) % photos.length;

  function doSwap() {
    // Crossfade: show back, hide front
    backLayer.classList.add('visible');
    frontLayer.classList.remove('visible');

    setTimeout(() => {
      // After transition: rotate layers, preload next-next
      [frontLayer, backLayer] = [backLayer, frontLayer];
      idx = nextIdx;
      preloadBack(photos[preloadIdx]);
      scheduleSlide();
    }, FADE_MS + 50);
  }

  // Ensure the next image is ready in backLayer
  if (backLayer.src.endsWith(nextFilename) && backLayer.complete && backLayer.naturalWidth > 0) {
    doSwap();
  } else {
    backLayer.onload = () => { backLayer.onload = null; doSwap(); };
    backLayer.onerror = () => { backLayer.onerror = null; scheduleSlide(); };
    backLayer.src = photoSrc(nextFilename);
  }
}

function startSlideshow(list) {
  hasPhotos = true;
  noPhotos.hidden = true;

  photos = shuffle([...list]);
  idx = 0;

  // Show first photo immediately
  frontLayer.onload = () => {
    frontLayer.onload = null;
    frontLayer.classList.add('visible');
    // Preload second photo into back layer
    preloadBack(photos[1]);
    scheduleSlide();
  };
  frontLayer.onerror = () => { frontLayer.onerror = null; scheduleSlide(); };
  frontLayer.src = photoSrc(photos[0]);

  // Front might already be cached
  if (frontLayer.complete && frontLayer.naturalWidth > 0) {
    frontLayer.onload();
  }
}

function mergeNewPhotos(newList) {
  const known = new Set(photos);
  const added = shuffle(newList.filter(f => !known.has(f)));
  if (added.length === 0) return;
  // Insert new photos right after the current position
  photos.splice(idx + 1, 0, ...added);
}

// ── Manifest polling ───────────────────────────────────────────────────────

async function pollManifest() {
  const data = await apiFetch('/api/photos');
  if (!data) return;

  if (data.count === 0) {
    if (hasPhotos) {
      // All photos deleted — show no-photos card
      hasPhotos = false;
      clearTimeout(slideTimer);
      frontLayer.classList.remove('visible');
      backLayer.classList.remove('visible');
      photos = [];
      showNoPhotos();
    }
    return;
  }

  if (!hasPhotos) {
    startSlideshow(data.photos);
  } else {
    mergeNewPhotos(data.photos);
  }
}

async function showNoPhotos() {
  noPhotos.hidden = false;
  const status = await apiFetch('/api/status');
  if (status && status.pi_ip) {
    uploadUrl.textContent = 'http://' + status.pi_ip + ':5000/upload';
  }
}

async function init() {
  const data = await apiFetch('/api/photos');
  if (!data || data.count === 0) {
    await showNoPhotos();
  } else {
    startSlideshow(data.photos);
  }
  setInterval(pollManifest, MANIFEST_POLL_MS);
}

// ── Weather ────────────────────────────────────────────────────────────────

async function updateWeather() {
  const d = await apiFetch('/api/weather');
  if (d) renderWeather(d);
}

function renderWeather(d) {
  const cur = d.current || {};
  const loc = d.location || {};

  // Main block (left sidebar)
  const iconEl = document.getElementById('w-icon');
  if (cur.icon) {
    iconEl.src = '/static/icons/' + cur.icon + '.svg';
    iconEl.alt = cur.condition || '';
    iconEl.hidden = false;
  }

  document.getElementById('w-temp').textContent =
    cur.temp != null ? Math.round(cur.temp) + '°' : '—';
  document.getElementById('w-condition').textContent = cur.condition || '';
  document.getElementById('w-city').textContent =
    [loc.city, loc.country].filter(Boolean).join(', ') +
    (loc.approximate ? ' (approx.)' : '');

  // Stats
  document.getElementById('w-feels').textContent =
    cur.feels_like != null ? Math.round(cur.feels_like) + '°' : '—';
  document.getElementById('w-humidity').textContent =
    cur.humidity != null ? cur.humidity + '%' : '—';
  document.getElementById('w-wind').textContent =
    cur.wind_kmh != null ? Math.round(cur.wind_kmh) + ' km/h' : '—';

  // AQI card (colored accent driven by --aqi-color)
  document.getElementById('aqi-value').textContent =
    cur.aqi_us != null ? cur.aqi_us : '—';
  document.getElementById('aqi-label').textContent = cur.aqi_label || ' ';
  if (cur.aqi_color) {
    document.getElementById('aqi-card').style.setProperty('--aqi-color', cur.aqi_color);
  }

  // Rain strip
  const strip = document.getElementById('rain-strip');
  strip.innerHTML = '';
  (d.hourly_next12 || []).forEach(h => {
    const bar = document.createElement('div');
    bar.className = 'rain-bar';
    const pct = Math.max(0, Math.min(100, h.rain_prob || 0));
    bar.style.height = pct + '%';
    bar.title = (h.time ? h.time.slice(11, 16) : '') + ': ' + pct + '%';
    strip.appendChild(bar);
  });

  // Daily forecast
  const fc = document.getElementById('daily-forecast');
  fc.innerHTML = '';
  (d.daily || []).forEach(day => {
    const dt   = day.date ? new Date(day.date + 'T12:00:00') : null;
    const lbl  = dt ? dt.toLocaleDateString(undefined, { weekday: 'short' }) : '';
    const icon = day.icon || 'cloudy';
    const el   = document.createElement('div');
    el.className = 'fc-day';
    el.innerHTML =
      '<div class="fc-label">' + lbl + '</div>' +
      '<img class="fc-icon" src="/static/icons/' + icon + '.svg" alt="">' +
      '<div class="fc-temps">' +
        '<span class="fc-max">' + (day.tmax != null ? Math.round(day.tmax) + '°' : '—') + '</span>' +
        '<span class="fc-min">' + (day.tmin != null ? Math.round(day.tmin) + '°' : '—') + '</span>' +
      '</div>' +
      '<div class="fc-rain">' + (day.rain_prob_max || 0) + '%</div>';
    fc.appendChild(el);
  });

  // Stale indicator
  document.getElementById('w-stale').hidden = !d.stale;
}

updateWeather();
setInterval(updateWeather, WEATHER_POLL_MS);

init();
