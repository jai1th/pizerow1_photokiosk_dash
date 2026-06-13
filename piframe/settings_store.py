"""Persistent settings file — data/cache/settings.json.

Stores user-overrideable runtime config (location, calendar URLs).
Thread-safe merge-on-write; values survive service restarts.
"""
import json
import logging
import threading
from pathlib import Path

import config

log = logging.getLogger(__name__)
_lock = threading.Lock()
_PATH: Path = config.CACHE_DIR / "settings.json"


def load() -> dict:
    try:
        return json.loads(_PATH.read_text())
    except Exception:
        return {}


def update(patch: dict) -> dict:
    """Merge patch into existing settings and persist. Returns new full state."""
    with _lock:
        current = load()
        current.update(patch)
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2))
        tmp.replace(_PATH)
        log.info("settings updated: %s", list(patch.keys()))
        return current
