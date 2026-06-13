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
