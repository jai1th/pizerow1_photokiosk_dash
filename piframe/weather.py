import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WMO weather code → (label, icon)
# ---------------------------------------------------------------------------

WMO_CODES = {
    0:  ("Clear sky",           "clear-day"),
    1:  ("Mainly clear",        "clear-day"),
    2:  ("Partly cloudy",       "partly-cloudy-day"),
    3:  ("Overcast",            "cloudy"),
    45: ("Fog",                 "fog"),
    48: ("Icy fog",             "fog"),
    51: ("Light drizzle",       "drizzle"),
    53: ("Drizzle",             "drizzle"),
    55: ("Heavy drizzle",       "drizzle"),
    56: ("Freezing drizzle",    "drizzle"),
    57: ("Heavy freezing drizzle", "drizzle"),
    61: ("Light rain",          "rain"),
    63: ("Rain",                "rain"),
    65: ("Heavy rain",          "rain"),
    66: ("Freezing rain",       "rain"),
    67: ("Heavy freezing rain", "rain"),
    71: ("Light snow",          "snow"),
    73: ("Snow",                "snow"),
    75: ("Heavy snow",          "snow"),
    77: ("Snow grains",         "snow"),
    80: ("Light showers",       "showers-day"),
    81: ("Showers",             "showers-day"),
    82: ("Heavy showers",       "showers-day"),
    85: ("Snow showers",        "snow"),
    86: ("Heavy snow showers",  "snow"),
    95: ("Thunderstorm",        "thunderstorm"),
    96: ("Thunderstorm w/ hail", "thunderstorm"),
    99: ("Thunderstorm w/ heavy hail", "thunderstorm"),
}

# ---------------------------------------------------------------------------
# US AQI bands
# ---------------------------------------------------------------------------

AQI_BANDS = [
    (50,  "Good",             "#00e400"),
    (100, "Moderate",         "#ffff00"),
    (150, "Unhealthy for SG", "#ff7e00"),
    (200, "Unhealthy",        "#ff0000"),
    (300, "Very Unhealthy",   "#8f3f97"),
    (500, "Hazardous",        "#7e0023"),
]


def _aqi_label(us_aqi: int | None) -> tuple[str, str]:
    if us_aqi is None:
        return ("Unknown", "#888888")
    for threshold, label, color in AQI_BANDS:
        if us_aqi <= threshold:
            return (label, color)
    return ("Hazardous", "#7e0023")


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

def get_location() -> dict:
    # User-set override from the upload-page settings takes precedence.
    try:
        from piframe import settings_store
        ov = settings_store.load().get("location_override")
        if ov and ov.get("lat") and ov.get("lon"):
            return ov
    except Exception:
        pass

    if config.LOCATION_CACHE.exists():
        try:
            with open(config.LOCATION_CACHE) as f:
                data = json.load(f)
            if data.get("lat") and data.get("lon"):
                return data
        except (json.JSONDecodeError, OSError):
            pass

    log.info("fetching geolocation from ip-api.com")
    try:
        r = requests.get(
            "http://ip-api.com/json/",
            params={"fields": "status,lat,lon,city,country"},
            timeout=config.WEATHER_TIMEOUT_SECS,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "success":
            loc = {
                "lat": data["lat"],
                "lon": data["lon"],
                "city": data.get("city", ""),
                "country": data.get("country", ""),
                "approximate": False,
            }
            _write_json(config.LOCATION_CACHE, loc)
            return loc
    except Exception as exc:
        log.warning("geolocation failed: %s", exc)

    log.warning("using fallback coordinates")
    return {
        "lat": config.FALLBACK_LAT,
        "lon": config.FALLBACK_LON,
        "city": "",
        "country": "",
        "approximate": True,
    }


# ---------------------------------------------------------------------------
# Weather fetch + merge
# ---------------------------------------------------------------------------

def _fetch_forecast(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,rain,weather_code,wind_speed_10m,is_day"
        ),
        "hourly": "precipitation_probability,precipitation,temperature_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "auto",
        "forecast_days": 3,
    }
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=params,
        timeout=config.WEATHER_TIMEOUT_SECS,
    )
    r.raise_for_status()
    return r.json()


def _fetch_aqi(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "us_aqi,european_aqi,pm2_5,pm10,ozone",
        "timezone": "auto",
    }
    r = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params=params,
        timeout=config.WEATHER_TIMEOUT_SECS,
    )
    r.raise_for_status()
    return r.json()


def _merge(loc: dict, forecast: dict, aqi: dict) -> dict:
    cur = forecast.get("current", {})
    wmo = cur.get("weather_code", 0)
    condition, icon = WMO_CODES.get(wmo, ("Unknown", "cloudy"))

    # Night variant for clear/partly-cloudy icons
    if not cur.get("is_day", True):
        icon = icon.replace("-day", "-night")

    aqi_cur = aqi.get("current", {})
    us_aqi = aqi_cur.get("us_aqi")
    aqi_label, aqi_color = _aqi_label(us_aqi)

    # Hourly next 12 entries
    hourly = forecast.get("hourly", {})
    h_times = hourly.get("time", [])[:12]
    h_prob  = hourly.get("precipitation_probability", [])[:12]
    h_precip= hourly.get("precipitation", [])[:12]
    h_temp  = hourly.get("temperature_2m", [])[:12]

    hourly_next12 = [
        {
            "time":      h_times[i] if i < len(h_times) else "",
            "rain_prob": h_prob[i]  if i < len(h_prob)  else 0,
            "precip_mm": h_precip[i] if i < len(h_precip) else 0.0,
            "temp":      h_temp[i]  if i < len(h_temp)  else None,
        }
        for i in range(len(h_times))
    ]

    # Daily 3-day
    daily_raw = forecast.get("daily", {})
    d_dates  = daily_raw.get("time", [])
    d_tmax   = daily_raw.get("temperature_2m_max", [])
    d_tmin   = daily_raw.get("temperature_2m_min", [])
    d_prob   = daily_raw.get("precipitation_probability_max", [])
    d_codes  = daily_raw.get("weather_code", [])

    daily = [
        {
            "date":         d_dates[i] if i < len(d_dates) else "",
            "tmax":         d_tmax[i]  if i < len(d_tmax)  else None,
            "tmin":         d_tmin[i]  if i < len(d_tmin)  else None,
            "rain_prob_max":d_prob[i]  if i < len(d_prob)  else 0,
            "icon":         WMO_CODES.get(d_codes[i] if i < len(d_codes) else 0, ("", "cloudy"))[1],
        }
        for i in range(len(d_dates))
    ]

    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    if config.UNITS == "fahrenheit" and temp is not None:
        temp = temp * 9 / 5 + 32
        feels = feels * 9 / 5 + 32 if feels is not None else None

    return {
        "location": {"city": loc.get("city", ""), "country": loc.get("country", ""), "approximate": loc.get("approximate", False)},
        "current": {
            "temp":             round(temp, 1) if temp is not None else None,
            "feels_like":       round(feels, 1) if feels is not None else None,
            "humidity":         cur.get("relative_humidity_2m"),
            "condition":        condition,
            "icon":             icon,
            "wind_kmh":         cur.get("wind_speed_10m"),
            "is_day":           bool(cur.get("is_day", True)),
            "precipitation_mm": cur.get("precipitation", 0.0),
            "aqi_us":           us_aqi,
            "aqi_eu":           aqi_cur.get("european_aqi"),
            "aqi_label":        aqi_label,
            "aqi_color":        aqi_color,
            "pm2_5":            aqi_cur.get("pm2_5"),
            "pm10":             aqi_cur.get("pm10"),
        },
        "hourly_next12": hourly_next12,
        "daily":         daily,
        "timezone":      forecast.get("timezone", ""),  # IANA tz for this location
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
        "stale":         False,
    }


def get_weather() -> dict:
    # Return cached payload if fresh
    if config.WEATHER_CACHE.exists():
        try:
            with open(config.WEATHER_CACHE) as f:
                cached = json.load(f)
            fetched = datetime.fromisoformat(cached["fetched_at"])
            age = (datetime.now(timezone.utc) - fetched).total_seconds()
            if age < config.WEATHER_REFRESH_SECS:
                return cached
        except (KeyError, ValueError, OSError, json.JSONDecodeError):
            pass

    loc = get_location()
    try:
        forecast = _fetch_forecast(loc["lat"], loc["lon"])
        aqi      = _fetch_aqi(loc["lat"], loc["lon"])
        payload  = _merge(loc, forecast, aqi)
        _write_json(config.WEATHER_CACHE, payload)
        return payload
    except Exception as exc:
        log.warning("weather fetch failed: %s", exc)
        # Serve stale cache rather than an empty panel
        if config.WEATHER_CACHE.exists():
            try:
                with open(config.WEATHER_CACHE) as f:
                    stale = json.load(f)
                stale["stale"] = True
                return stale
            except Exception:
                pass
        return {"stale": True, "error": str(exc)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)
