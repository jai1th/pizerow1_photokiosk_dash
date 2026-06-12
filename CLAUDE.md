# CLAUDE.md — PiFrame Kiosk: Photo Slideshow + Weather Dashboard for Raspberry Pi Zero W 1

## What this project is

A self-contained web kiosk for a **Raspberry Pi Zero W (v1)** running **DietPi**. On boot, the Pi launches a full-screen browser pointed at a locally hosted web app that:

1. Cycles through photos stored in a local folder, full screen, with crossfade transitions.
2. Overlays a weather panel: current conditions, AQI, and rainfall/precipitation forecast for the Pi's location, auto-detected from its public IP.
3. Hosts an upload page on the LAN so anyone on the network can drop new photos onto the Pi from a phone or laptop. New photos enter the slideshow rotation automatically, no restart needed.

## Hard constraints — read before writing any code

The target is the **original Pi Zero W**, not the Zero 2 W. This dictates everything:

| Constraint | Value | Consequence |
|---|---|---|
| CPU | BCM2835, **single core ARMv6** @ 1GHz | No heavy JS frameworks, no client-side image processing, no WebGL |
| RAM | **512MB** total (shared with GPU) | Browser + server + OS must fit in ~400MB usable |
| Architecture | **armv6l** (armhf userland) | **Modern Chromium is NOT available** — RPi dropped ARMv6 Chromium builds. Many pip packages with Rust/C extensions lack armv6 wheels |
| Network | 2.4GHz WiFi only | Uploads of large photos take time; upload UI must show progress |
| Storage | microSD | Minimize writes; cache thumbnails once, don't regenerate |

### Browser decision (the "Chromium kiosk" requirement)

The user asked for a Chromium-style web kiosk. On ARMv6 there are two valid paths. **Implement Path A. Document Path B in the README.**

- **Path A (primary): Cog + WPE WebKit.** `apt install cog` (pulls `libwpewebkit`). Cog is a kiosk-only browser shell designed for embedded devices. It renders directly to DRM/KMS — **no X server, no desktop, no window manager needed**, which saves ~100MB+ of RAM versus an X-based setup. Modern WebKit engine: full ES2020 JS, CSS transitions, flexbox, fetch. Launch: `cog -P drm http://127.0.0.1:5000/`.
  - If `cog` is unavailable or broken on the installed DietPi/Debian version, fall back to **surf** (webkit2gtk) on a minimal X stack (`xserver-xorg`, `xinit`, no WM) launched via `startx` with `surf -F http://127.0.0.1:5000/`.
- **Path B (documented only): real Chromium kiosk.** Works only if the hardware is swapped for a **Pi Zero 2 W** (same form factor, ARMv8). Then DietPi's native `dietpi-autostart` → "Chromium kiosk" option applies, with `SOFTWARE_CHROMIUM_AUTOSTART_URL=http://127.0.0.1:5000/` in `dietpi.txt`. The web app itself must be engine-agnostic so this swap requires zero code changes.

### Frontend rules forced by ARMv6

- **Vanilla HTML/CSS/JS only.** No React, no Vue, no Tailwind CDN, no bundler. One HTML file, one CSS file, one JS file per page.
- Crossfade = two stacked `<img>` elements toggling CSS `opacity` with a `transition`. Never use JS-driven animation loops, canvas, or filters.
- The browser must **never decode full-resolution photos**. The backend pre-scales every image to display resolution (default 1920×1080, configurable) and the slideshow only ever loads from the scaled cache.
- Preload exactly one image ahead. Never more.
- All external API logic lives on the **backend**. The frontend only ever fetches `http://127.0.0.1:5000/api/...`. This keeps browser JS trivial and sidesteps CORS entirely.
- Weather panel re-fetches every 15 minutes via `setInterval`; slideshow polls the photo manifest every 60 seconds and diffs it.
- Add a `?nocursor` friendly design: no hover-dependent UI. Hide the cursor with CSS (`cursor: none` on body).

## Architecture

```
┌─────────────────────────── Pi Zero W (DietPi) ───────────────────────────┐
│                                                                          │
│  systemd: piframe.service          systemd: piframe-kiosk.service        │
│  ┌──────────────────────────┐      ┌───────────────────────────────┐     │
│  │ Flask app (waitress)     │◄─────│ Cog (WPE WebKit, DRM/KMS)     │     │
│  │ 0.0.0.0:5000             │ HTTP │ full-screen → 127.0.0.1:5000  │     │
│  │                          │      └───────────────────────────────┘     │
│  │ /            slideshow   │                                            │
│  │ /upload      upload page │      data/photos/originals/  (uploads)     │
│  │ /api/photos  manifest    │      data/photos/display/    (scaled cache)│
│  │ /api/weather cached JSON │      data/cache/weather.json               │
│  │ /photos/<f>  scaled imgs │      data/cache/location.json              │
│  └──────┬───────────────────┘                                            │
│         │ outbound HTTPS (server-side only, cached)                      │
└─────────┼────────────────────────────────────────────────────────────────┘
          ├── ip-api.com/json            (geolocation from public IP, no key)
          ├── api.open-meteo.com         (forecast: temp, precip, rain prob)
          └── air-quality-api.open-meteo.com  (AQI: us_aqi/european_aqi, PM2.5, PM10)
```

LAN users browse to `http://<pi-ip>:5000/upload` to add/delete photos.

## Tech stack (pinned decisions — do not substitute)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3 (system python3 on DietPi) | Pure-python deps have armv6 wheels on piwheels |
| Web framework | **Flask** | Lightweight, zero compiled deps. **Do NOT use FastAPI**: pydantic-core (Rust) wheels are unreliable on armv6 |
| WSGI server | **waitress** | Pure Python, production-grade, multi-threaded (needed so an upload doesn't block weather requests). Do NOT use gunicorn (fork model wastes RAM) or `flask run` |
| Image scaling | **Pillow** | armv6 wheels exist on piwheels; use `Image.draft()` + `thumbnail()` for low-RAM JPEG decode |
| HTTP client | **requests** | Pure Python |
| Geolocation | `http://ip-api.com/json/?fields=status,lat,lon,city,country` | Free non-commercial, no API key. Cache result to disk forever (re-fetch only on failure or manual reset) — the Pi doesn't move |
| Weather | **Open-Meteo Forecast API** `api.open-meteo.com/v1/forecast` | Free, no key, no signup. Params: `current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,rain,weather_code,wind_speed_10m,is_day&hourly=precipitation_probability,precipitation,temperature_2m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code&timezone=auto&forecast_days=3` |
| AQI | **Open-Meteo Air Quality API** `air-quality-api.open-meteo.com/v1/air-quality` | Same provider, no key. Params: `current=us_aqi,european_aqi,pm2_5,pm10,ozone&timezone=auto` |
| Kiosk browser | **Cog (WPE WebKit)**, fallback surf | See browser decision above |
| Process mgmt | **systemd** units | DietPi native; auto-restart on crash |
| Frontend | Vanilla HTML/CSS/JS | See ARMv6 rules |

Install Python deps with piwheels (DietPi/RPi pip is preconfigured for it): `pip3 install flask waitress pillow requests`.

Attribution requirement: Open-Meteo data is CC BY 4.0 — render a small "Weather by Open-Meteo.com" credit in the weather panel footer.

## Repository layout

```
piframe/
├── CLAUDE.md
├── README.md                  # setup guide incl. DietPi steps + Pi Zero 2 W / Chromium variant
├── requirements.txt
├── config.py                  # all tunables: port, display resolution, slide interval,
│                              #   fade duration, weather refresh, units (C/F), paths
├── app.py                     # Flask app factory + waitress entrypoint
├── piframe/
│   ├── __init__.py
│   ├── routes_pages.py        # GET /  (slideshow), GET /upload
│   ├── routes_api.py          # /api/photos, /api/weather, /api/status, /api/upload, /api/photos/<name> DELETE
│   ├── photos.py              # scan, validate, scale-on-ingest, manifest, safe filenames
│   ├── weather.py             # geolocate-once + fetch/merge forecast & AQI + disk cache + WMO code → label/icon map
│   └── util.py
├── static/
│   ├── slideshow.css / slideshow.js
│   ├── upload.css / upload.js
│   └── icons/                 # inline SVG weather icons (no icon font, no CDN)
├── templates/
│   ├── slideshow.html
│   └── upload.html
├── data/                      # gitignored; created at first run
│   ├── photos/originals/
│   ├── photos/display/
│   └── cache/
├── deploy/
│   ├── piframe.service
│   ├── piframe-kiosk.service
│   └── install.sh             # idempotent: apt deps, pip deps, copy units, enable services
└── tests/
    ├── test_photos.py
    └── test_weather.py        # mock all HTTP with responses/unittest.mock — tests must run offline
```

## Build order — strictly two stages

### STAGE 1: Backend (complete and verified before any frontend work)

Build in this order, testing each piece on a dev machine (mock the Pi paths via `config.py`):

1. **Scaffold + config.** Flask app factory, `config.py` with env-var overrides (`PIFRAME_PORT`, `PIFRAME_PHOTO_DIR`, `PIFRAME_DISPLAY_W/H`, `PIFRAME_SLIDE_SECONDS`, `PIFRAME_UNITS`). Auto-create `data/` tree on startup.
2. **Photo module** (`photos.py`):
   - Allowed types: jpg/jpeg/png/webp (validate by magic bytes via Pillow `verify()`, not extension). Reject > 30MB.
   - `secure_filename` + collision handling (`name.jpg` → `name_1.jpg`).
   - **Ingest pipeline**: on upload (and on startup for any original lacking a display copy), produce `data/photos/display/<name>.jpg`: `Image.draft('RGB', (W,H))` then `thumbnail((W,H))`, save JPEG quality 85, progressive. Apply EXIF orientation. Strip EXIF from the display copy. Process **one image at a time** (a lock/queue) — concurrent Pillow jobs will OOM a Zero W.
   - Manifest: `GET /api/photos` → `{"photos":[...display filenames...], "count":N, "updated":ts}` sorted by mtime.
   - Serve scaled images at `/photos/<filename>` with strong cache headers (`Cache-Control: max-age=86400`, ETag) — filenames are content-stable.
3. **Upload/delete API**: `POST /api/upload` (multipart, multiple files, returns per-file ok/error JSON), `DELETE /api/photos/<name>` (removes original + display copy). Path-traversal safe.
4. **Weather module** (`weather.py`):
   - `get_location()`: read `data/cache/location.json`; if absent call ip-api.com, persist `{lat, lon, city, country}`. On failure use `PIFRAME_FALLBACK_LAT/LON` from config and flag `"approximate": true`.
   - `get_weather()`: if `data/cache/weather.json` younger than 15 min, return it. Else fetch forecast + air-quality (two GETs, 10s timeout each), merge into one normalized payload:
     ```json
     {
       "location": {"city": "...", "country": "..."},
       "current": {"temp": 21.4, "feels_like": 20.1, "humidity": 55,
                    "condition": "Partly cloudy", "icon": "partly-cloudy-day",
                    "wind_kmh": 12.4, "is_day": true,
                    "precipitation_mm": 0.0,
                    "aqi_us": 42, "aqi_eu": 31, "aqi_label": "Good", "pm2_5": 8.1, "pm10": 14.0},
       "hourly_next12": [{"time": "...", "rain_prob": 30, "precip_mm": 0.2, "temp": 19.0}, ...],
       "daily": [{"date": "...", "tmin": 12, "tmax": 23, "rain_prob_max": 60, "icon": "rain"}, ...],
       "fetched_at": "ISO8601", "stale": false
     }
     ```
   - Map WMO `weather_code` → human label + icon name (single dict in `weather.py`). Map US AQI → label/color band (Good/Moderate/USG/Unhealthy/Very Unhealthy/Hazardous).
   - **On any fetch failure, serve the last cached payload with `"stale": true`** — the kiosk must never show a blank panel because the WiFi blipped.
5. **Status endpoint**: `GET /api/status` → uptime, photo count, last weather fetch, disk free, Pi IP (handy for the upload page footer and debugging).
6. **Entrypoint**: `app.py` runs waitress with `threads=4`. Verify: `curl` every endpoint, upload via `curl -F`, confirm scaled output dimensions, confirm weather cache file behavior (delete it, watch refetch).

**Stage 1 exit criteria:** all endpoints pass manual curl checks + `pytest` green offline.

### STAGE 2: Frontend

1. **Slideshow page (`/`)**:
   - Black background, two absolutely-positioned full-viewport `<img>` layers, `object-fit: contain`.
   - JS: fetch manifest → shuffle (Fisher-Yates) → loop. Every `SLIDE_SECONDS` (injected from config into the template): set hidden img's `src` to next photo, on its `load` event swap opacities (1.5s ease CSS transition), then preload the following one.
   - Re-fetch manifest every 60s; if changed, merge new photos into the remaining rotation without restarting the cycle.
   - Weather overlay: semi-transparent dark panel, bottom-left. Big temp + condition icon + city; row of chips for feels-like, humidity, wind, **AQI (value + label, color-coded band)**; a "Rain next 12h" strip showing hourly rain-probability as simple CSS bar heights (divs — **no chart library**); 3-day forecast row. Small clock (HH:MM) top-right updated every 30s. `stale: true` → subtle ⚠ on the panel.
   - Zero photos → friendly card: "Add photos at http://<pi-ip>:5000/upload" (IP from `/api/status`).
   - `cursor: none`; no scrollbars (`overflow: hidden`).
2. **Upload page (`/upload`)** — viewed from phones/laptops, NOT the kiosk, so it can be slightly richer but still vanilla JS:
   - Drag-and-drop zone + file picker (`multiple`, `accept="image/*"`); per-file progress bars via `XMLHttpRequest.upload.onprogress` (2.4GHz WiFi = slow, progress is mandatory); sequential upload queue (don't parallel-blast the Zero W).
   - Thumbnail grid of current photos (reuse `/photos/<name>` scaled images) with a delete button + confirm.
   - Mobile-first responsive CSS.
3. **Verify both pages in a desktop browser at narrow + 1080p widths before moving to deployment.**

### STAGE 3 (deployment glue, part of Stage 2 deliverable)

1. `deploy/piframe.service`:
   ```ini
   [Unit]
   Description=PiFrame backend
   After=network-online.target
   Wants=network-online.target
   [Service]
   User=dietpi
   WorkingDirectory=/opt/piframe
   ExecStart=/usr/bin/python3 /opt/piframe/app.py
   Restart=always
   RestartSec=5
   [Install]
   WantedBy=multi-user.target
   ```
2. `deploy/piframe-kiosk.service`: `ExecStartPre` curl-wait loop until `127.0.0.1:5000/api/status` responds, then `ExecStart=/usr/bin/cog -P drm http://127.0.0.1:5000/`. `Restart=always`. Needs `seatd`/render group access on DRM (add user to `video`/`render` groups in `install.sh`).
3. `install.sh` (idempotent): `apt install -y cog python3-pip libopenjp2-7` (Pillow runtime dep), `pip3 install -r requirements.txt`, rsync project to `/opt/piframe`, install + enable both units, print the Pi's IP and upload URL.
4. README: flashing DietPi, first-boot config, `dietpi.txt` headless WiFi setup, GPU memory split note (`gpu_mem=64` minimum for DRM rendering), the install one-liner, and the **Pi Zero 2 W / Chromium variant** (Path B) section.

## Coding standards

- Python: type hints, no global mutable state outside explicit module-level caches with locks, `logging` (not print), graceful handling of every external HTTP call (timeout + try/except + cached fallback).
- No database. Filesystem + JSON cache files are the entire persistence layer. This is deliberate — keep it.
- No authentication on the upload page (trusted home LAN). Note this in README with a sentence on why and what to do if exposed beyond the LAN (don't).
- Frontend JS: ES6, no transpiling, no external CDNs — **the kiosk must render with zero internet** (weather panel just shows stale/empty state).
- Every config value used by the frontend (slide interval, fade time) is injected via the Jinja template from `config.py` — single source of truth.
- Tests mock all network I/O; CI/dev machines and the Pi can run `pytest` offline.

## Performance budget (verify on-device at the end)

- Backend RSS at idle: < 60MB. Cog RSS: < 200MB. Total system: comfortably under 450MB, zero swap thrash after 24h.
- Slideshow transition with 1080p pre-scaled JPEGs: no visible stutter.
- Weather payload < 10KB; manifest < 5KB at 500 photos.
- Upload of a 10MB photo over WiFi completes with live progress and the image enters rotation within ~90s (ingest scaling on a Zero W is slow — that's fine, it's queued).

## Things Claude Code must NOT do

- Do not install or assume Chromium on the Pi Zero W 1 (ARMv6 — unsupported). Path B is Zero 2 W only.
- Do not use FastAPI/uvicorn/pydantic, Node.js, or any frontend framework/bundler.
- Do not add websockets, SSE, or server push — polling is sufficient and lighter.
- Do not generate multiple thumbnail sizes; one display-resolution cache per photo.
- Do not call Open-Meteo or ip-api from the browser; backend proxy + cache only.
- Do not run X11/desktop packages in Path A; Cog renders via DRM/KMS directly.