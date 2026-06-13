import base64
import socket
from datetime import date
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, render_template, request, make_response

import config
from piframe import photos, weather

pages_bp = Blueprint("pages", __name__)

# ---------------------------------------------------------------------------
# Inlined static assets
#
# This board's ARMv6 WebKit intermittently deadlocks on subresource loads
# (the WTF flock bug that also kills fetch/XHR): the server returns the CSS /
# JS / icon 200, but the body never reaches the renderer, so the page shows
# unstyled (raw document flow). The document HTML itself always renders, so we
# inline the layout-critical assets straight into it — no separate request to
# deadlock. slideshow.css / slideshow.js stay the single source of truth on
# disk; we just read and embed them at render time. Only photos remain as
# <img> subresources (too large to inline); if one blips, the frame still holds.
# ---------------------------------------------------------------------------

_STATIC = config.BASE_DIR / "static"


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


# Cached at import — these don't change at runtime, and the service restarts
# (re-importing this module) whenever they're redeployed. Minimises SD reads.
_INLINE_CSS = _read_text(_STATIC / "slideshow.css")
_INLINE_JS = _read_text(_STATIC / "slideshow.js")
_ICONS = {p.stem: _read_text(p) for p in sorted((_STATIC / "icons").glob("*.svg"))}


def _pi_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@lru_cache(maxsize=16)
def _encode_photo(filename: str, mtime_ns: int) -> str:
    """Read a display JPEG and return a base64 data URI. Cached by
    (filename, mtime) so repeated reloads don't re-encode the same photos;
    the mtime in the key auto-invalidates a replaced file. Bounded to 16
    entries (~8 MB worst case) so a large library can't blow up RAM."""
    raw = (config.DISPLAY_DIR / filename).read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _photo_data_uri(filename: str) -> str:
    # Photos are inlined as data URIs rather than <img src="/photos/..">: this
    # board's ARMv6 WebKit intermittently deadlocks on subresource loads, which
    # left the slideshow stage black. Inlining makes the page 100% self-
    # contained (zero subresources) — the reliable navigation path delivers it.
    try:
        st = (config.DISPLAY_DIR / filename).stat()
        return _encode_photo(filename, st.st_mtime_ns)
    except Exception:
        return ""


def _weekday(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%a")
    except Exception:
        return ""


def _rnd(v) -> str:
    return str(round(v)) if isinstance(v, (int, float)) else "--"


def _format_weather(wx: dict) -> dict:
    """Pre-format the weather payload into display strings so the template
    stays trivial (and so all data is server-rendered — no browser fetch,
    which deadlocks the WTF lock in this ARMv6 WebKit build)."""
    cur = wx.get("current") or {}
    loc = wx.get("location") or {}

    daily = []
    for d in (wx.get("daily") or [])[:3]:
        daily.append({
            "label": _weekday(d.get("date", "")),
            "icon":  d.get("icon") or "cloudy",
            "tmax":  _rnd(d.get("tmax")),
            "tmin":  _rnd(d.get("tmin")),
            "rain":  d.get("rain_prob_max") or 0,
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
        "daily":     daily,
        "hourly":    hourly,
        "stale":     bool(wx.get("stale")),
    }


@pages_bp.route("/")
def slideshow():
    manifest = photos.get_manifest()
    all_photos = manifest["photos"]
    count = manifest["count"]

    # Rotate a bounded batch across reloads via ?o=<offset>.
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

    html = render_template(
        "slideshow.html",
        slide_seconds=config.SLIDE_SECONDS,
        fade_ms=config.FADE_MS,
        photos=batch,
        photo_count=count,
        next_offset=next_offset,
        w=_format_weather(weather.get_weather()),
        pi_ip=_pi_ip(),
        inline_css=_INLINE_CSS,
        inline_js=_INLINE_JS,
        icons=_ICONS,
    )
    # The page reloads itself to refresh weather/photos, so it must never be
    # served from the browser cache — always render fresh.
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@pages_bp.route("/upload")
def upload():
    return render_template("upload.html")
