import base64
import socket
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, render_template, request, make_response

import config
from piframe import photos, weather, calendar as cal

pages_bp = Blueprint("pages", __name__)

# ---------------------------------------------------------------------------
# Inlined static assets
#
# This board's ARMv6 WebKit intermittently deadlocks on subresource loads
# (WTF flock bug): CSS/JS/icons/photos are ALL inlined into the HTML so the
# page is 100% self-contained with zero subresource requests.
# ---------------------------------------------------------------------------

_STATIC = config.BASE_DIR / "static"


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


_INLINE_CSS = _read_text(_STATIC / "slideshow.css")
_INLINE_JS  = _read_text(_STATIC / "slideshow.js")
_ICONS      = {p.stem: _read_text(p) for p in sorted((_STATIC / "icons").glob("*.svg"))}


def _build_font_face_css() -> str:
    font_map = [
        ("IBM Plex Mono",  300, "IBMPlexMono-Light.woff2"),
        ("IBM Plex Mono",  400, "IBMPlexMono-Regular.woff2"),
        ("IBM Plex Sans",  400, "IBMPlexSans-Regular.woff2"),
        ("IBM Plex Sans",  500, "IBMPlexSans-Medium.woff2"),
        ("IBM Plex Serif", 400, "IBMPlexSerif-Regular.woff2"),
    ]
    parts = []
    for family, weight, filename in font_map:
        p = _STATIC / "fonts" / filename
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        parts.append(
            f'@font-face{{font-family:"{family}";font-weight:{weight};font-style:normal;'
            f'font-display:swap;src:url("data:font/woff2;base64,{b64}") format("woff2");}}'
        )
    return "\n".join(parts)


_FONT_FACE_CSS = _build_font_face_css()


# ---------------------------------------------------------------------------
# Photo encoding (inline as data URIs — no /photos/ subresource requests)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=16)
def _encode_photo(filename: str, mtime_ns: int) -> str:
    raw = (config.DISPLAY_DIR / filename).read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _photo_data_uri(filename: str) -> str:
    try:
        st = (config.DISPLAY_DIR / filename).stat()
        return _encode_photo(filename, st.st_mtime_ns)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Data formatters
# ---------------------------------------------------------------------------

def _pi_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _weekday(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%a")
    except Exception:
        return ""


def _rnd(v) -> str:
    return str(round(v)) if isinstance(v, (int, float)) else "--"


def _format_weather(wx: dict) -> dict:
    cur = wx.get("current") or {}
    loc = wx.get("location") or {}
    use_f = config.UNITS == "fahrenheit"

    daily = []
    for d in (wx.get("daily") or [])[:3]:
        daily.append({
            "label": _weekday(d.get("date", "")),
            "icon":  d.get("icon") or "cloudy",
            "hi":    _rnd(d.get("tmax")),
            "lo":    _rnd(d.get("tmin")),
        })

    hourly = []
    for h in (wx.get("hourly_next12") or [])[:12]:
        try:
            hourly.append(max(0, min(100, int(h.get("rain_prob") or 0))))
        except (TypeError, ValueError):
            hourly.append(0)

    city = ", ".join([x for x in [loc.get("city"), loc.get("country")] if x])
    if loc.get("approximate"):
        city = (city + " (approx.)").strip()

    return {
        "has_data":  bool(cur),
        "temp":      _rnd(cur.get("temp")),
        "feels":     _rnd(cur.get("feels_like")),
        "humidity":  str(cur.get("humidity")) if cur.get("humidity") is not None else "--",
        "condition": cur.get("condition") or "",
        "icon":      cur.get("icon") or "cloudy",
        "wind":      _rnd(cur.get("wind_kmh")),
        "city":      city,
        "aqi":       str(cur.get("aqi_us")) if cur.get("aqi_us") is not None else "--",
        "aqi_label": cur.get("aqi_label") or "",
        "aqi_color": cur.get("aqi_color") or "#888888",
        "units":     "°F" if use_f else "°C",
        "daily":     daily,
        "hourly":    hourly,
        "stale":     bool(wx.get("stale")),
    }


def _format_status(wx: dict, manifest: dict) -> dict:
    count = manifest.get("count", 0)
    if not wx.get("current"):
        return {"level": "err", "title": "No weather data", "sub": f"{count} photos"}
    if wx.get("stale"):
        return {"level": "warn", "title": "Weather stale", "sub": f"Cached data · {count} photos"}
    fetched = wx.get("fetched_at", "")
    age_str = ""
    if fetched:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
            mins = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
            age_str = f"Synced {mins}m ago · " if mins < 60 else ""
        except Exception:
            pass
    return {"level": "ok", "title": "All good", "sub": f"{age_str}{count} photos"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pages_bp.route("/")
def slideshow():
    manifest = photos.get_manifest()
    all_photos = manifest["photos"]
    count = manifest["count"]

    try:
        offset = int(request.args.get("o", 0))
    except (TypeError, ValueError):
        offset = 0

    if count > 0:
        offset = offset % count
        n = min(config.SLIDE_BATCH, count)
        names = [all_photos[(offset + i) % count] for i in range(n)]
        batch = [u for u in (_photo_data_uri(f) for f in names) if u]
        next_offset = (offset + n) % count
    else:
        batch = []
        next_offset = 0

    wx = weather.get_weather()
    w = _format_weather(wx)
    status = _format_status(wx, manifest)
    events = cal.get_events()

    html = render_template(
        "slideshow.html",
        slide_seconds=config.SLIDE_SECONDS,
        fade_ms=config.FADE_MS,
        photos=batch,
        photo_count=count,
        next_offset=next_offset,
        w=w,
        status=status,
        events=events,
        tz_main=config.TZ_MAIN,
        tz_zones=config.TZ_ZONES,
        pi_ip=_pi_ip(),
        font_face_css=_FONT_FACE_CSS,
        inline_css=_INLINE_CSS,
        inline_js=_INLINE_JS,
        icons=_ICONS,
        backdrop_filter=config.BACKDROP_FILTER,
    )
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@pages_bp.route("/upload")
def upload():
    return render_template("upload.html")
