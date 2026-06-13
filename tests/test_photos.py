import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    display = tmp_path / "display"
    cache   = tmp_path / "cache"
    for d in (display, cache):
        d.mkdir()

    import config
    monkeypatch.setattr(config, "ORIGINALS_DIR",    tmp_path / "originals")
    monkeypatch.setattr(config, "DISPLAY_DIR",      display)
    monkeypatch.setattr(config, "CACHE_DIR",        cache)
    monkeypatch.setattr(config, "PHOTOS_REGISTRY",  cache / "photos.json")
    monkeypatch.setattr(config, "WEATHER_CACHE",    cache / "weather.json")
    monkeypatch.setattr(config, "DISPLAY_W",        320)
    monkeypatch.setattr(config, "DISPLAY_H",        240)
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 30 * 1024 * 1024)

    yield tmp_path


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
# ingest (synchronous) + dedup
# ---------------------------------------------------------------------------

def test_ingest_creates_display_copy(tmp_dirs):
    import config
    from piframe.photos import ingest
    p = tmp_dirs / "source.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        ingest(content_hash, f, "source.jpg")

    # Synchronous: display copy and registry entry exist immediately
    assert (config.DISPLAY_DIR / f"{content_hash}.jpg").exists()
    from piframe.photos import registry_has
    assert registry_has(content_hash)


def test_ingest_is_immediately_visible_in_manifest(tmp_dirs):
    from piframe.photos import ingest, get_manifest
    p = tmp_dirs / "instant.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        ingest(content_hash, f, "instant.jpg")

    manifest = get_manifest()
    assert manifest["count"] == 1
    assert f"{content_hash}.jpg" in manifest["photos"]


def test_duplicate_detected_after_ingest(tmp_dirs):
    """is_known() returns True after ingest() completes."""
    from piframe import photos
    p = tmp_dirs / "dup.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "dup.jpg")

    assert photos.is_known(content_hash)


def test_ingest_idempotent_same_hash(tmp_dirs):
    """Calling ingest() twice with the same hash is safe and produces one entry."""
    import config
    from piframe.photos import ingest, get_manifest
    p = tmp_dirs / "same.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        ingest(content_hash, f, "same.jpg")
    with open(p, "rb") as f:
        ingest(content_hash, f, "same.jpg")  # second call is a no-op

    assert get_manifest()["count"] == 1


def test_registry_survives_restart(tmp_dirs):
    import config
    from piframe import photos
    p = tmp_dirs / "persist.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "persist.jpg")

    reg = json.loads(config.PHOTOS_REGISTRY.read_text())
    assert content_hash in reg
    assert reg[content_hash]["original_name"] == "persist.jpg"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_manifest_excludes_missing_display(tmp_dirs):
    import config
    reg = {"deadbeef12345678deadbeef12345678": {"original_name": "ghost.jpg", "cached_at": "2026-01-01T00:00:00+00:00"}}
    config.PHOTOS_REGISTRY.write_text(json.dumps(reg))

    from piframe import photos
    manifest = photos.get_manifest()
    assert manifest["count"] == 0
    assert manifest["photos"] == []


def test_manifest_includes_completed_photo(tmp_dirs):
    from piframe import photos
    p = tmp_dirs / "real.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "real.jpg")

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

    photos.delete_photo(content_hash)

    assert not (config.DISPLAY_DIR / f"{content_hash}.jpg").exists()
    assert not photos.registry_has(content_hash)


# ---------------------------------------------------------------------------
# Startup repair scan
# ---------------------------------------------------------------------------

def test_repair_registers_orphaned_display(tmp_dirs):
    """Repair scan registers a display copy that exists on disk but not in the registry."""
    import config
    from piframe import photos

    p = tmp_dirs / "orphan.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    # Simulate: display copy exists but registry is empty
    shutil.copy(p, config.DISPLAY_DIR / f"{content_hash}.jpg")
    assert not photos.registry_has(content_hash)

    photos.start_repair_scan()
    assert _wait_for_registry(content_hash), "repair scan never registered the display copy"


def test_repair_skips_already_registered(tmp_dirs):
    """Repair scan does not clobber an existing registry entry."""
    import config
    from piframe import photos

    p = tmp_dirs / "known.jpg"
    _make_jpeg(p)
    content_hash = _hash_file(p)

    with open(p, "rb") as f:
        photos.ingest(content_hash, f, "known.jpg")

    original_entry = json.loads(config.PHOTOS_REGISTRY.read_text())[content_hash]

    photos.start_repair_scan()
    time.sleep(0.2)  # let the thread run

    current_entry = json.loads(config.PHOTOS_REGISTRY.read_text())[content_hash]
    assert current_entry["cached_at"] == original_entry["cached_at"]
