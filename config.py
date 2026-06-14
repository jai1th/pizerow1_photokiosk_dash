import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Server
PORT = int(os.getenv("PIFRAME_PORT", 5000))
WSGI_THREADS = 4

# Paths
PHOTO_DIR = Path(os.getenv("PIFRAME_PHOTO_DIR", BASE_DIR / "data" / "photos"))
ORIGINALS_DIR = PHOTO_DIR / "originals"
DISPLAY_DIR = PHOTO_DIR / "display"
CACHE_DIR = Path(os.getenv("PIFRAME_CACHE_DIR", BASE_DIR / "data" / "cache"))
PHOTOS_REGISTRY = CACHE_DIR / "photos.json"
WEATHER_CACHE = CACHE_DIR / "weather.json"
LOCATION_CACHE = CACHE_DIR / "location.json"

# Display
DISPLAY_W = int(os.getenv("PIFRAME_DISPLAY_W", 1920))
DISPLAY_H = int(os.getenv("PIFRAME_DISPLAY_H", 1080))
JPEG_QUALITY = 85

# Slideshow
SLIDE_SECONDS = int(os.getenv("PIFRAME_SLIDE_SECONDS", 10))
FADE_MS = int(os.getenv("PIFRAME_FADE_MS", 1500))
# Photos rendered into each page load (server-rendered, navigation-loaded).
# The page crossfades through this batch, then reloads for the next batch.
# Kept small to bound memory on the Pi Zero W (each ~1080p JPEG decodes large).
SLIDE_BATCH = int(os.getenv("PIFRAME_SLIDE_BATCH", 6))

# Weather
WEATHER_REFRESH_SECS = 15 * 60
WEATHER_TIMEOUT_SECS = 10
UNITS = os.getenv("PIFRAME_UNITS", "celsius")  # "celsius" or "fahrenheit"
FALLBACK_LAT = float(os.getenv("PIFRAME_FALLBACK_LAT", 0.0))
FALLBACK_LON = float(os.getenv("PIFRAME_FALLBACK_LON", 0.0))

# Upload
MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # 30 MB
ALLOWED_MIMETYPES = {"image/jpeg", "image/png", "image/webp"}

# Timezones — main is the Pi's local TZ ("" = JS browser local); extras are
# shown as chips in the clock rail.  Format: "Label:IANA/Zone" comma-separated.
TZ_MAIN = os.getenv("PIFRAME_TZ_MAIN", "")
TZ_ZONES_RAW = os.getenv("PIFRAME_TZ_ZONES", "Panama:America/Panama,Detroit:America/Detroit")
TZ_ZONES = [
    {"label": p.split(":")[0], "tz": p.split(":", 1)[1]}
    for p in TZ_ZONES_RAW.split(",") if ":" in p
]

# How often slideshow.js polls /api/photos/version for fast new-photo detection.
VERSION_POLL_SECONDS = int(os.getenv("PIFRAME_VERSION_POLL_SECONDS", 10))

# Calendar — optional .ics URL (e.g. Google Calendar secret iCal address).
# Leave empty to show no events.
CALENDAR_ICS_URL = os.getenv("PIFRAME_CALENDAR_ICS_URL", "")
CALENDAR_CACHE = CACHE_DIR / "calendar.json"
CALENDAR_REFRESH_SECS = 15 * 60

# UI — backdrop-filter (frosted glass blur) is GPU-heavy on ARMv6/compositing-
# disabled WebKit. Set PIFRAME_BACKDROP_FILTER=1 on a faster board (Zero 2 W).
BACKDROP_FILTER = os.getenv("PIFRAME_BACKDROP_FILTER", "0") == "1"
