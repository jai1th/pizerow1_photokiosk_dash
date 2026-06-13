"""Calendar module — fetches today's events from a .ics URL, caches to disk.

Returns [] if CALENDAR_ICS_URL is not configured. Stale cache is served on
fetch failures. Parser is pure-Python (no external deps) so it works on ARMv6.
"""
import json
import logging
import re
import threading
import time
from datetime import date, datetime, timezone

import config

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _parse_ics(text: str, today: date) -> list[dict]:
    """Extract VEVENT entries for today, return [{time, mins, title}] sorted."""
    events = []
    blocks = re.split(r"BEGIN:VEVENT", text, flags=re.IGNORECASE)
    for block in blocks[1:]:
        end_match = re.search(r"END:VEVENT", block, re.IGNORECASE)
        if end_match:
            block = block[: end_match.start()]

        # Unfold continuation lines (RFC 5545)
        block = re.sub(r"\r?\n[ \t]", "", block)

        def get(key: str) -> str:
            m = re.search(rf"^{key}[^:]*:(.*)", block, re.MULTILINE | re.IGNORECASE)
            return m.group(1).strip() if m else ""

        dtstart_raw = get("DTSTART")
        summary = get("SUMMARY")
        if not dtstart_raw or not summary:
            continue

        try:
            # All-day: DTSTART;VALUE=DATE:20250613 or DTSTART:20250613
            if re.match(r"^\d{8}$", dtstart_raw):
                ev_date = datetime.strptime(dtstart_raw, "%Y%m%d").date()
                ev_time_str = "All day"
                ev_mins = 0
            elif re.match(r"^\d{8}T\d{6}Z?$", dtstart_raw):
                fmt = "%Y%m%dT%H%M%SZ" if dtstart_raw.endswith("Z") else "%Y%m%dT%H%M%S"
                dt_utc = datetime.strptime(dtstart_raw, fmt).replace(tzinfo=timezone.utc)
                dt_local = dt_utc.astimezone()
                ev_date = dt_local.date()
                h, m = dt_local.hour, dt_local.minute
                ap = "AM" if h < 12 else "PM"
                h12 = h % 12 or 12
                ev_time_str = f"{h12}:{m:02d} {ap}"
                ev_mins = h * 60 + m
            else:
                continue
        except Exception:
            continue

        if ev_date != today:
            continue

        events.append({"time": ev_time_str, "mins": ev_mins, "title": summary})

    return sorted(events, key=lambda e: e["mins"])


def _ics_url() -> str:
    """Return the active ICS URL: settings (google first, then outlook) or env."""
    try:
        from piframe import settings_store
        s = settings_store.load()
        return s.get("calendar_google_ics") or s.get("calendar_outlook_ics") or config.CALENDAR_ICS_URL
    except Exception:
        return config.CALENDAR_ICS_URL


def get_events() -> list[dict]:
    """Return today's events. Returns [] if no calendar is configured."""
    url = _ics_url()
    if not url:
        return []

    with _lock:
        cache_path = config.CALENDAR_CACHE
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                if time.time() - cached.get("fetched_at", 0) < config.CALENDAR_REFRESH_SECS:
                    return cached.get("events", [])
            except Exception:
                pass

        try:
            import requests
            resp = requests.get(url, timeout=config.WEATHER_TIMEOUT_SECS)
            resp.raise_for_status()
            events = _parse_ics(resp.text, date.today())
            cache_path.write_text(json.dumps({"events": events, "fetched_at": time.time()}))
            log.info("calendar: fetched %d events for today", len(events))
            return events
        except Exception as exc:
            log.warning("calendar fetch error: %s", exc)
            if cache_path.exists():
                try:
                    return json.loads(cache_path.read_text()).get("events", [])
                except Exception:
                    pass
            return []
