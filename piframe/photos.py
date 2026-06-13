import json
import logging
import queue
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

import config
from piframe.util import sha256_fileobj

log = logging.getLogger(__name__)

_registry_lock = threading.Lock()
_pending_lock = threading.Lock()
_pending_hashes: set[str] = set()

_ingest_queue: queue.Queue = queue.Queue()
_worker_thread: threading.Thread | None = None


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
    """True if hash is fully registered OR currently queued/in-progress."""
    with _pending_lock:
        if content_hash in _pending_hashes:
            return True
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
# Background ingest worker
# ---------------------------------------------------------------------------

def _ingest_one(content_hash: str, original_path: Path) -> None:
    """Scale original → display copy. Called only from the ingest worker."""
    display_path = config.DISPLAY_DIR / f"{content_hash}.jpg"
    if display_path.exists():
        return

    log.info("ingesting %s", content_hash)
    w, h = config.DISPLAY_W, config.DISPLAY_H
    with Image.open(original_path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.draft("RGB", (w, h))
        img.thumbnail((w, h), Image.LANCZOS)
        clean = Image.new(img.mode, img.size)
        clean.paste(img)
        tmp = display_path.with_suffix(".tmp")
        clean.save(tmp, "JPEG", quality=config.JPEG_QUALITY, progressive=True, optimize=True)
    tmp.replace(display_path)
    log.info("ingested %s → %s", content_hash, display_path.name)


def _worker_loop() -> None:
    while True:
        job = _ingest_queue.get()
        content_hash, original_path, original_name = job
        try:
            _ingest_one(content_hash, original_path)
            _register(content_hash, original_name)
        except Exception as exc:
            log.error("ingest failed for %s: %s", content_hash, exc)
            original_path.unlink(missing_ok=True)
        finally:
            with _pending_lock:
                _pending_hashes.discard(content_hash)
            _ingest_queue.task_done()


def start_ingest_worker() -> None:
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="ingest-worker")
    _worker_thread.start()


# ---------------------------------------------------------------------------
# Public ingest entry point (non-blocking)
# ---------------------------------------------------------------------------

def ingest(content_hash: str, src_fileobj, original_name: str) -> None:
    """
    Save src_fileobj to originals and enqueue scaling for the background worker.
    Returns immediately; the display copy appears once the worker finishes.
    src_fileobj must be seeked to 0 before calling.
    """
    ext = Path(original_name).suffix.lower() or ".jpg"
    original_path = config.ORIGINALS_DIR / f"{content_hash}{ext}"

    with open(original_path, "wb") as dst:
        shutil.copyfileobj(src_fileobj, dst)

    with _pending_lock:
        _pending_hashes.add(content_hash)
    _ingest_queue.put((content_hash, original_path, original_name))


# ---------------------------------------------------------------------------
# Startup repair scan
# ---------------------------------------------------------------------------

def _repair_scan() -> None:
    """Enqueue any original that is missing its display copy."""
    for orig in config.ORIGINALS_DIR.iterdir():
        if not orig.is_file():
            continue
        content_hash = orig.stem
        display = config.DISPLAY_DIR / f"{content_hash}.jpg"
        if not display.exists():
            log.info("repair: queuing %s", content_hash)
            with _pending_lock:
                _pending_hashes.add(content_hash)
            _ingest_queue.put((content_hash, orig, orig.name))


def start_repair_scan() -> None:
    t = threading.Thread(target=_repair_scan, daemon=True, name="repair-scan")
    t.start()


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

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
    """Remove originals file, display copy, and registry entry."""
    for orig in config.ORIGINALS_DIR.iterdir():
        if orig.stem == content_hash:
            orig.unlink(missing_ok=True)
            break

    display = config.DISPLAY_DIR / f"{content_hash}.jpg"
    display.unlink(missing_ok=True)

    _deregister(content_hash)
