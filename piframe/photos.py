import json
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

import config

log = logging.getLogger(__name__)

_registry_lock = threading.Lock()
_write_lock    = threading.Lock()


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    if config.PHOTOS_REGISTRY.exists():
        try:
            with open(config.PHOTOS_REGISTRY) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("photos registry corrupt, starting fresh")
    return {}


def _save_registry(registry: dict) -> None:
    tmp = config.PHOTOS_REGISTRY.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(registry, f, indent=2)
    tmp.replace(config.PHOTOS_REGISTRY)


def registry_has(content_hash: str) -> bool:
    with _registry_lock:
        return content_hash in _load_registry()


def is_known(content_hash: str) -> bool:
    return registry_has(content_hash)


def _register(content_hash: str, original_name: str) -> None:
    with _registry_lock:
        registry = _load_registry()
        registry[content_hash] = {
            "original_name": original_name,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_registry(registry)


def _deregister(content_hash: str) -> None:
    with _registry_lock:
        registry = _load_registry()
        registry.pop(content_hash, None)
        _save_registry(registry)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_image(path: Path) -> None:
    """Raise ValueError if file is not a valid supported image."""
    size = path.stat().st_size
    if size > config.MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large: {size} bytes")
    try:
        with Image.open(path) as img:
            img.verify()
    except Exception as exc:
        raise ValueError(f"invalid image: {exc}") from exc
    # Re-open to check format (verify() closes the file handle)
    with Image.open(path) as img:
        fmt = (img.format or "").lower()
        if fmt not in ("jpeg", "png", "webp"):
            raise ValueError(f"unsupported format: {fmt}")


# ---------------------------------------------------------------------------
# Ingest (synchronous — client already scaled to display resolution)
# ---------------------------------------------------------------------------

def ingest(content_hash: str, src_fileobj, original_name: str) -> None:
    """
    Write src_fileobj directly to display/ and register it.
    The caller is responsible for pre-scaling (done via canvas on the client).
    src_fileobj must be seeked to 0 before calling.
    """
    display_path = config.DISPLAY_DIR / f"{content_hash}.jpg"
    with _write_lock:
        if display_path.exists():
            return
        tmp = display_path.with_suffix(".tmp")
        with open(tmp, "wb") as dst:
            shutil.copyfileobj(src_fileobj, dst)
        tmp.replace(display_path)
    _register(content_hash, original_name)
    log.info("stored display copy %s (%s)", content_hash, original_name)


# ---------------------------------------------------------------------------
# Startup repair scan
# ---------------------------------------------------------------------------

def _repair_scan() -> None:
    """Register any display copy on disk that is absent from the registry."""
    for display in config.DISPLAY_DIR.iterdir():
        if not display.is_file() or display.suffix != ".jpg":
            continue
        content_hash = display.stem
        if len(content_hash) != 32:
            continue
        if not registry_has(content_hash):
            log.info("repair: registering orphaned display copy %s", content_hash)
            _register(content_hash, display.name)


def start_repair_scan() -> None:
    t = threading.Thread(target=_repair_scan, daemon=True, name="repair-scan")
    t.start()


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_version() -> dict:
    """Cheap directory stat — count + max mtime, no image reads.

    Used by the slideshow version-poll endpoint so JS can detect new photos
    with a tiny response (~30 bytes) without fetching the full manifest.
    """
    try:
        entries = [
            f for f in config.DISPLAY_DIR.iterdir()
            if f.is_file() and f.suffix == ".jpg"
        ]
    except OSError:
        return {"version": "0", "count": 0}
    count = len(entries)
    if not entries:
        return {"version": "0", "count": 0}
    max_mtime = max(int(f.stat().st_mtime_ns) for f in entries)
    return {"version": f"{count}_{max_mtime}", "count": count}


def get_manifest() -> dict:
    """
    Return only hashes that have both a registry entry and a completed display copy.
    Sorted by cached_at (oldest first).
    """
    with _registry_lock:
        registry = _load_registry()

    photos = []
    for content_hash, meta in registry.items():
        display = config.DISPLAY_DIR / f"{content_hash}.jpg"
        if display.exists():
            photos.append({
                "hash": content_hash,
                "filename": f"{content_hash}.jpg",
                "original_name": meta.get("original_name", ""),
                "cached_at": meta.get("cached_at", ""),
            })

    photos.sort(key=lambda p: p["cached_at"])
    return {
        "photos": [p["filename"] for p in photos],
        "count": len(photos),
        "updated": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_photo(content_hash: str) -> None:
    """Remove display copy and registry entry."""
    display = config.DISPLAY_DIR / f"{content_hash}.jpg"
    display.unlink(missing_ok=True)
    _deregister(content_hash)
