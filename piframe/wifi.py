"""WiFi state and provisioning — a thin wrapper over the piframe-netctl helper.

Everything privileged lives in deploy/piframe-netctl, reached through a
narrowly-scoped sudoers rule. This module never touches the interface itself,
so the Flask process stays unprivileged.

The one piece of real logic here is that `join` is fire-and-forget. Switching
to the target network tears down the hotspot the caller is connected through,
so the HTTP response can never reach them — the request would simply hang
until it timed out, and the user would have no idea whether it worked. Instead
the switch runs on a background thread and the outcome is written to
data/cache/wifi_join.json, which the setup page reads when the user comes back.
"""
import json
import logging
import subprocess
import threading
import time

import config

log = logging.getLogger(__name__)

NETCTL = "/opt/piframe/deploy/piframe-netctl"
JOIN_RESULT = config.CACHE_DIR / "wifi_join.json"

# A scan takes several seconds and monopolises the radio, so serve repeats
# from cache. The list of nearby networks does not change meaningfully faster.
SCAN_TTL_SECS = 60

# status() shells out, and the captive-portal 404 handler calls it on every
# unknown path. A few seconds of staleness is invisible; forking per request
# on a single-core ARMv6 board is not.
STATUS_TTL_SECS = 5
_status_lock = threading.Lock()
_status_cache = {"at": 0.0, "data": None}
_scan_lock = threading.Lock()
_scan_cache = {"at": 0.0, "networks": []}
_join_lock = threading.Lock()
_join_running = False


def _netctl(*args, timeout=90):
    """Invoke the helper. Returns parsed JSON, or None on any failure."""
    try:
        p = subprocess.run(
            ["sudo", "-n", NETCTL, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("netctl %s: %s", args[0], exc)
        return None
    if not p.stdout.strip():
        log.warning("netctl %s -> rc=%d %s", args[0], p.returncode,
                    p.stderr.strip()[:200])
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        log.warning("netctl %s: unparseable output %r", args[0], p.stdout[:200])
        return None


def status(max_age: float = STATUS_TTL_SECS) -> dict:
    """Current network mode. Always returns a dict, never raises.

    mode is one of: client (associated), ap (hotspot up), down (neither),
    unknown (the helper is missing or the sudoers rule is not installed).
    Pass max_age=0 to force a fresh read.
    """
    with _status_lock:
        cached = _status_cache["data"]
        if cached is not None and time.time() - _status_cache["at"] < max_age:
            return cached

    data = _netctl("status", timeout=30)
    if data is None:
        return {
            "mode": "unknown", "ssid": "", "ip": "", "online": False,
            "hotspot_ssid": config.HOTSPOT_SSID,
        }
    with _status_lock:
        _status_cache["data"] = data
        _status_cache["at"] = time.time()
    return data


def in_setup_mode() -> bool:
    return status().get("mode") == "ap"


def scan(force: bool = False) -> list:
    """Nearby networks, strongest first.

    Returns the cached list while the hotspot is up: hostapd owns the radio
    then and a live scan comes back empty, which would blank the network
    picker at exactly the moment it is needed.
    """
    with _scan_lock:
        fresh = time.time() - _scan_cache["at"] < SCAN_TTL_SECS
        if fresh and not force:
            return _scan_cache["networks"]

    data = _netctl("scan", timeout=90)
    if data is None or data.get("error"):
        if data and data.get("error"):
            log.info("scan unavailable: %s", data["error"])
        return _scan_cache["networks"]

    with _scan_lock:
        _scan_cache["networks"] = data.get("networks", [])
        _scan_cache["at"] = time.time()
        return _scan_cache["networks"]


def last_join_result() -> dict:
    try:
        return json.loads(JOIN_RESULT.read_text())
    except Exception:
        return {}


def _record_join(ssid: str, ok: bool, error: str = "") -> None:
    payload = {
        "ssid": ssid, "ok": ok, "error": error,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        tmp = JOIN_RESULT.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(JOIN_RESULT)
    except OSError as exc:
        log.warning("could not record join result: %s", exc)


def _join_worker(ssid: str, psk: str) -> None:
    global _join_running
    try:
        log.info("joining %s", ssid)
        p = subprocess.run(
            ["sudo", "-n", NETCTL, "join", ssid, psk],
            capture_output=True, text=True,
            timeout=int(config.HOTSPOT_JOIN_TIMEOUT_SECS) + 90,
        )
        ok = p.returncode == 0
        # netctl already rolled back to the hotspot on failure; the message is
        # only here so the setup page can say why when the user rejoins.
        _record_join(ssid, ok, "" if ok else p.stderr.strip()[-300:])
        log.info("join %s: %s", ssid, "ok" if ok else "failed")
    except subprocess.TimeoutExpired:
        _record_join(ssid, False, "join timed out")
        log.warning("join %s timed out", ssid)
    except Exception as exc:
        _record_join(ssid, False, str(exc))
        log.warning("join %s errored: %s", ssid, exc)
    finally:
        with _join_lock:
            _join_running = False


def start_join(ssid: str, psk: str) -> tuple:
    """Kick off a join in the background. Returns (accepted, message).

    Rejects a second attempt while one is in flight — overlapping switches
    would race over wpa_supplicant.conf and could leave the backup file from
    one attempt overwriting the good config of another.
    """
    global _join_running
    if not ssid:
        return False, "ssid is required"
    if psk and not (8 <= len(psk) <= 63):
        return False, "password must be 8-63 characters"
    with _join_lock:
        if _join_running:
            return False, "a join is already in progress"
        _join_running = True
    threading.Thread(
        target=_join_worker, args=(ssid, psk), daemon=True, name="wifi-join"
    ).start()
    return True, "joining"
