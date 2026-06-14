import io
import logging
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path

import requests as _requests
from flask import Blueprint, jsonify, request, send_file, abort

import config
from piframe import photos, weather, settings_store
from piframe.util import sha256_fileobj

api_bp = Blueprint("api", __name__)
log = logging.getLogger(__name__)

_start_time = time.time()


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------

@api_bp.route("/api/photos", methods=["GET"])
def api_photos():
    return jsonify(photos.get_manifest())


@api_bp.route("/api/photos/version", methods=["GET"])
def api_photos_version():
    """Lightweight version token — count + max mtime, no image reads.

    JS polls this every VERSION_POLL_SECONDS and only fetches the full manifest
    (triggering a page reload) when the version string changes.
    """
    resp = jsonify(photos.get_version())
    resp.headers["Cache-Control"] = "no-store"
    return resp


@api_bp.route("/photos/<path:filename>")
def serve_photo(filename):
    # Reject any path that escapes the display dir
    safe = Path(filename).name
    if safe != filename or not safe.endswith(".jpg"):
        abort(400)
    path = config.DISPLAY_DIR / safe
    if not path.exists():
        abort(404)
    etag = f"{int(path.stat().st_mtime_ns):x}-{path.stat().st_size}"
    response = send_file(path, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "max-age=86400, immutable"
    response.headers["ETag"] = etag
    return response


@api_bp.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("file")
    if not files:
        return jsonify({"error": "no files provided"}), 400

    results = []
    for f in files:
        result = _handle_single_upload(f)
        results.append(result)

    # 202 if everything accepted; 207 if any file was a duplicate or error
    all_accepted = all(r.get("status") == "accepted" for r in results)
    return jsonify({"results": results}), 202 if all_accepted else 207


def _handle_single_upload(fileobj) -> dict:
    original_name = fileobj.filename or "upload"
    try:
        # Stream to a temp file while computing hash — avoids loading into RAM
        with tempfile.NamedTemporaryFile(delete=False, dir=config.CACHE_DIR) as tmp:
            tmp_path = Path(tmp.name)
            size = 0
            h = __import__("hashlib").sha256()
            for chunk in iter(lambda: fileobj.read(65536), b""):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    tmp_path.unlink(missing_ok=True)
                    return {"original_name": original_name, "status": "error", "error": "file too large"}
                h.update(chunk)
                tmp.write(chunk)

        content_hash = h.hexdigest()[:32]

        # Dedup: reject if already registered OR currently in the ingest queue
        if photos.is_known(content_hash):
            tmp_path.unlink(missing_ok=True)
            return {"original_name": original_name, "status": "duplicate", "hash": content_hash}

        # Validate magic bytes before committing anything to originals/
        try:
            photos.validate_image(tmp_path)
        except ValueError as exc:
            tmp_path.unlink(missing_ok=True)
            return {"original_name": original_name, "status": "error", "error": str(exc)}

        # Write display copy directly (pre-scaled by the client)
        with open(tmp_path, "rb") as src:
            photos.ingest(content_hash, src, original_name)
        tmp_path.unlink(missing_ok=True)

        return {"original_name": original_name, "status": "accepted", "hash": content_hash}

    except Exception as exc:
        log.exception("upload error for %s", original_name)
        return {"original_name": original_name, "status": "error", "error": str(exc)}


@api_bp.route("/api/photos/<path:content_hash>", methods=["DELETE"])
def api_delete_photo(content_hash):
    safe = Path(content_hash).name
    if safe != content_hash or len(safe) != 32:
        abort(400)
    if not photos.registry_has(safe):
        abort(404)
    photos.delete_photo(safe)
    return "", 204


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@api_bp.route("/api/settings", methods=["GET"])
def api_settings_get():
    s = settings_store.load()
    return jsonify({
        "location_override":   s.get("location_override"),
        "calendar_google_ics": s.get("calendar_google_ics", ""),
        "calendar_outlook_ics":s.get("calendar_outlook_ics", ""),
        "slide_seconds":       s.get("slide_seconds", config.SLIDE_SECONDS),
        "photo_order":         s.get("photo_order", "oldest"),
    })


@api_bp.route("/api/settings/location", methods=["POST"])
def api_settings_location():
    data = request.get_json(force=True, silent=True) or {}

    if data.get("reset"):
        settings_store.update({"location_override": None})
        config.WEATHER_CACHE.unlink(missing_ok=True)
        config.LOCATION_CACHE.unlink(missing_ok=True)
        return jsonify({"status": "ok", "location_override": None})

    city = data.get("city", "").strip()
    if not city:
        return jsonify({"error": "city required"}), 400

    try:
        r = _requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=10,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return jsonify({"error": f"city not found: {city}"}), 404
        res = results[0]
        loc = {
            "lat": res["latitude"],
            "lon": res["longitude"],
            "city": res.get("name", city),
            "country": res.get("country", ""),
            "approximate": False,
        }
    except Exception as exc:
        log.warning("geocode failed: %s", exc)
        return jsonify({"error": str(exc)}), 502

    settings_store.update({"location_override": loc})
    config.WEATHER_CACHE.unlink(missing_ok=True)
    return jsonify({"status": "ok", "location_override": loc})


@api_bp.route("/api/settings/slideshow", methods=["POST"])
def api_settings_slideshow():
    data = request.get_json(force=True, silent=True) or {}
    patch = {}

    if "slide_seconds" in data:
        try:
            secs = int(data["slide_seconds"])
            if not (3 <= secs <= 300):
                return jsonify({"error": "slide_seconds must be 3–300"}), 400
            patch["slide_seconds"] = secs
        except (TypeError, ValueError):
            return jsonify({"error": "slide_seconds must be an integer"}), 400

    if "order" in data:
        order = str(data["order"])
        if order not in ("oldest", "newest", "random"):
            return jsonify({"error": "order must be oldest, newest, or random"}), 400
        patch["photo_order"] = order

    if not patch:
        return jsonify({"error": "provide slide_seconds and/or order"}), 400

    settings_store.update(patch)
    return jsonify({"status": "ok"})


@api_bp.route("/api/settings/calendar", methods=["POST"])
def api_settings_calendar():
    data = request.get_json(force=True, silent=True) or {}
    patch = {}
    if "google" in data:
        patch["calendar_google_ics"] = data["google"].strip()
    if "outlook" in data:
        patch["calendar_outlook_ics"] = data["outlook"].strip()
    if not patch:
        return jsonify({"error": "provide google and/or outlook key"}), 400
    settings_store.update(patch)
    config.CALENDAR_CACHE.unlink(missing_ok=True)
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

@api_bp.route("/api/weather", methods=["GET"])
def api_weather():
    return jsonify(weather.get_weather())


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@api_bp.route("/api/status", methods=["GET"])
def api_status():
    manifest = photos.get_manifest()
    disk = shutil.disk_usage(config.BASE_DIR)

    last_weather = None
    if config.WEATHER_CACHE.exists():
        try:
            import json
            with open(config.WEATHER_CACHE) as wf:
                wdata = json.load(wf)
            last_weather = wdata.get("fetched_at")
        except Exception:
            pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            pi_ip = s.getsockname()[0]
    except Exception:
        pi_ip = "unknown"

    return jsonify({
        "uptime_seconds": int(time.time() - _start_time),
        "photo_count": manifest["count"],
        "last_weather_fetch": last_weather,
        "disk_free_mb": disk.free // (1024 * 1024),
        "disk_total_mb": disk.total // (1024 * 1024),
        "pi_ip": pi_ip,
    })
