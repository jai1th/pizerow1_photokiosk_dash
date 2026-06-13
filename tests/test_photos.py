import hashlib
import json
import queue
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    originals = tmp_path / "originals"
    display   = tmp_path / "display"
    cache     = tmp_path / "cache"
    for d in (originals, display, cache):
        d.mkdir()

    import config
    monkeypatch.setattr(config, "ORIGINALS_DIR",    originals)
    monkeypatch.setattr(config, "DISPLAY_DIR",      display)
    monkeypatch.setattr(config, "CACHE_DIR",        cache)
    monkeypatch.setattr(config, "PHOTOS_REGISTRY",  cache / "photos.json")
    monkeypatch.setattr(config, "WEATHER_CACHE",    cache / "weather.json")
    monkeypatch.setattr(config, "DISPLAY_W",        320)
    monkeypatch.setattr(config, "DISPLAY_H",        240)
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 30 * 1024 * 1024)

    # Ensure worker is running; drain any leftover jobs from a prior test
    from piframe import photos
    photos.start_ingest_worker()
    _drain_queue(photos)

    yield tmp_path


def _drain_queue(photos_module) -> None:
    """Discard queued items left over from a prior test."""
    while True:
        try:
            photos_module._ingest_queue.get_nowait()
            photos_module._ingest_queue.task_done()
        except queue.Empty:
            break


def _wait_for_display(content_hash: str, timeout: float = 5.0) -> bool:
    import config
    deadline = time.time() + timeout
    while time.time() < deadline:
        if (config.DISPLAY_DIR / f"{content_hash}.jpg").exists():
            return True
        time.sleep(0.05)
    return False


def _wait_for_registry(content_hash: str, timeout: float = 5.0) -> bool:
    from piframe.photos import registry_has
    deadline = time.time() + timeout
    while time.time() < deadline:
        if registry_has(content_hash):
            return True
        time.sleep(0.05)
    return False


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:32]


def _make_jpeg(path: Path, width: int = 800, height: int = 600) -> None:
    Image.new("RGB", (width, height), color=(100, 150, 200)).save(path, "JPEG")


def _make_png(path: Path) -> None:
    Image.new("RGB", (400, 300), color=(10, 20, 30)).save(path, "PNG")


# ---------------------------------------------------------------------------
# validate_image
# ---------------------------------------------------------------------------

def test_validate_jpeg_ok(tmp_path):
    from piframe.photos import validate_image
    p = tmp_path / "ok.jpg"
    _make_jpeg(p)
    validate_image(p)


def test_validate_png_ok(tmp_path):
    from piframe.photos import validate_image
    p = tmp_path / "ok.png"
    _make_png(p)
    validate_image(p)


def test_validate_bad_magic_bytes(tmp_path):
    from piframe.photos import validate_image
    p = tmp_path / "fake.jpg"
    p.write_bytes(b"THIS IS NOT AN IMAGE AT ALL !!!!")
    with pytest.raises(ValueError, match="invalid image"):
        validate_image(p)


def test_validate_too_large(tmp_path, monkeypatch):
    import config
    from piframe.photos import validate_image
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 100)
    p = tmp_path / "big.jpg"
    _make_jpeg(p)
    with pytest.raises(ValueError, match="too large"):
        validate_image(p)


# ---------------------------------------------------------------------------
# ingest (async) + dedup
# ---------------------------------------------------------------------------

def test_ingest_creates_display_copy(tmp_dirs):
    import config
    from piframe.photos import ingest
    p = tmp_dirs / "source.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        ingest(content_hash, f, "source.jpg")

    assert _wait_for_display(content_hash), "display copy never appeared"
    assert _wait_for_registry(content_hash), "registry entry never appeared"

    with Image.open(config.DISPLAY_DIR / f"{content_hash}.jpg") as img:
        assert img.width <= config.DISPLAY_W
        assert img.height <= config.DISPLAY_H


def test_ingest_display_dimensions_scaled_down(tmp_dirs):
    import config
    from piframe.photos import ingest
    p = tmp_dirs / "big.jpg"
    _make_jpeg(p, width=4000, height=3000)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        ingest(content_hash, f, "big.jpg")

    assert _wait_for_display(content_hash), "display copy never appeared"
    with Image.open(config.DISPLAY_DIR / f"{content_hash}.jpg") as img:
        assert img.width <= config.DISPLAY_W
        assert img.height <= config.DISPLAY_H


def test_duplicate_detected_while_in_queue(tmp_dirs):
    """is_known() returns True immediately after ingest() enqueues, before worker finishes."""
    from piframe import photos
    p = tmp_dirs / "dup.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "dup.jpg")

    # Must be detectable as known before the display copy exists
    assert photos.is_known(content_hash)


def test_duplicate_detected_after_ingest_completes(tmp_dirs):
    """is_known() stays True after the worker registers the hash."""
    from piframe import photos
    p = tmp_dirs / "dup2.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "dup2.jpg")

    assert _wait_for_registry(content_hash)
    assert photos.is_known(content_hash)


def test_registry_survives_restart(tmp_dirs):
    import config
    from piframe import photos
    p = tmp_dirs / "persist.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "persist.jpg")

    assert _wait_for_registry(content_hash)
    reg = json.loads(config.PHOTOS_REGISTRY.read_text())
    assert content_hash in reg
    assert reg[content_hash]["original_name"] == "persist.jpg"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_manifest_excludes_pending_photo(tmp_dirs):
    """A photo that's enqueued but not yet scaled must not appear in the manifest."""
    import config
    from piframe import photos

    # Block the worker so the job stays in-progress
    blocked = threading.Event()
    original = photos._ingest_one

    def blocking_ingest_one(h, p):
        blocked.wait(timeout=5)
        return original(h, p)

    photos._ingest_one = blocking_ingest_one
    try:
        p = tmp_dirs / "pending.jpg"
        _make_jpeg(p)
        content_hash = _hash_file(p)
        with open(p, "rb") as f:
            photos.ingest(content_hash, f, "pending.jpg")

        # Give worker time to pick up and block
        time.sleep(0.15)
        manifest = photos.get_manifest()
        assert manifest["count"] == 0
    finally:
        blocked.set()
        photos._ingest_one = original


def test_manifest_excludes_missing_display(tmp_dirs):
    import config
    reg = {"deadbeef12345678deadbeef12345678": {"original_name": "ghost.jpg", "cached_at": "2026-01-01T00:00:00+00:00"}}
    config.PHOTOS_REGISTRY.write_text(json.dumps(reg))

    from piframe import photos
    manifest = photos.get_manifest()
    assert manifest["count"] == 0
    assert manifest["photos"] == []


def test_manifest_includes_completed_photo(tmp_dirs):
    import config
    from piframe import photos
    p = tmp_dirs / "real.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "real.jpg")

    assert _wait_for_display(content_hash)
    manifest = photos.get_manifest()
    assert manifest["count"] == 1
    assert f"{content_hash}.jpg" in manifest["photos"]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_removes_all_traces(tmp_dirs):
    import config
    from piframe import photos
    p = tmp_dirs / "del.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "del.jpg")

    assert _wait_for_display(content_hash)
    photos.delete_photo(content_hash)

    assert not (config.DISPLAY_DIR / f"{content_hash}.jpg").exists()
    assert not photos.registry_has(content_hash)


# ---------------------------------------------------------------------------
# Startup repair scan
# ---------------------------------------------------------------------------

def test_repair_ingest_orphaned_original(tmp_dirs):
    import config
    from piframe import photos

    p = tmp_dirs / "orphan.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    orig_dest = config.ORIGINALS_DIR / f"{content_hash}.jpg"
    shutil.copy(p, orig_dest)

    photos.start_repair_scan()
    assert _wait_for_display(content_hash), "repair scan never produced display copy"


# ---------------------------------------------------------------------------
# Weather responds while ingest is running
# ---------------------------------------------------------------------------

def test_weather_available_during_ingest(tmp_dirs, monkeypatch):
    """GET /api/weather must complete quickly while the ingest worker is blocked."""
    import config
    from piframe import photos
    from app import create_app

    # Pre-load a fresh weather cache so /api/weather never touches the network
    weather_payload = {
        "location": {"city": "Test", "country": "TC", "approximate": False},
        "current": {
            "temp": 20.0, "feels_like": 19.0, "humidity": 60,
            "condition": "Clear sky", "icon": "clear-day",
            "wind_kmh": 5.0, "is_day": True, "precipitation_mm": 0.0,
            "aqi_us": 30, "aqi_eu": 25, "aqi_label": "Good", "aqi_color": "#00e400",
            "pm2_5": 5.0, "pm10": 8.0,
        },
        "hourly_next12": [], "daily": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "stale": False,
    }
    config.WEATHER_CACHE.write_text(json.dumps(weather_payload))

    # Patch _ingest_one to block until we signal it
    ingest_started = threading.Event()
    ingest_release = threading.Event()
    original_ingest_one = photos._ingest_one

    def blocking_ingest_one(content_hash, original_path):
        ingest_started.set()
        assert ingest_release.wait(timeout=10), "test never released ingest"
        return original_ingest_one(content_hash, original_path)

    monkeypatch.setattr(photos, "_ingest_one", blocking_ingest_one)

    # Place an original and enqueue it directly (bypasses is_known check)
    p = tmp_dirs / "slow.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)
    orig_dest = config.ORIGINALS_DIR / f"{content_hash}.jpg"
    shutil.copy(p, orig_dest)
    photos._ingest_queue.put((content_hash, orig_dest, "slow.jpg"))

    # Wait for the worker to pick up the job and block inside _ingest_one
    assert ingest_started.wait(timeout=5), "ingest worker never started the job"

    # Weather endpoint must return while the worker is blocked
    app = create_app()
    client = app.test_client()
    t0 = time.time()
    resp = client.get("/api/weather")
    elapsed = time.time() - t0

    assert resp.status_code == 200
    assert elapsed < 2.0, f"/api/weather took {elapsed:.3f}s while ingest was blocking"

    # Unblock and let the job finish cleanly
    ingest_release.set()
    assert _wait_for_display(content_hash), "display copy never appeared after unblocking"
