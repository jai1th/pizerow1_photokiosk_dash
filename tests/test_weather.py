import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "CACHE_DIR",       tmp_path)
    monkeypatch.setattr(config, "WEATHER_CACHE",   tmp_path / "weather.json")
    monkeypatch.setattr(config, "LOCATION_CACHE",  tmp_path / "location.json")
    monkeypatch.setattr(config, "FALLBACK_LAT",    51.5)
    monkeypatch.setattr(config, "FALLBACK_LON",    -0.1)
    monkeypatch.setattr(config, "WEATHER_REFRESH_SECS", 900)
    monkeypatch.setattr(config, "UNITS",           "celsius")
    yield tmp_path


# ---------------------------------------------------------------------------
# Fixtures: minimal valid API responses
# ---------------------------------------------------------------------------

FORECAST_RESP = {
    "current": {
        "temperature_2m": 20.0,
        "apparent_temperature": 18.5,
        "relative_humidity_2m": 60,
        "precipitation": 0.0,
        "rain": 0.0,
        "weather_code": 2,
        "wind_speed_10m": 14.0,
        "is_day": 1,
    },
    "hourly": {
        "time": [f"2026-06-12T{h:02d}:00" for h in range(12)],
        "precipitation_probability": [10] * 12,
        "precipitation": [0.0] * 12,
        "temperature_2m": [19.0] * 12,
    },
    "daily": {
        "time": ["2026-06-12", "2026-06-13", "2026-06-14"],
        "temperature_2m_max": [22.0, 21.0, 20.0],
        "temperature_2m_min": [12.0, 11.0, 10.0],
        "precipitation_probability_max": [20, 40, 60],
        "weather_code": [2, 61, 63],
    },
}

AQI_RESP = {
    "current": {
        "us_aqi": 35,
        "european_aqi": 28,
        "pm2_5": 7.2,
        "pm10": 12.0,
        "ozone": 60.0,
    }
}

LOC_RESP = {
    "status": "success",
    "lat": 51.5,
    "lon": -0.1,
    "city": "London",
    "country": "United Kingdom",
}


def _mock_response(data: dict, status=200) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = data
    m.raise_for_status = MagicMock()
    return m


# ---------------------------------------------------------------------------
# get_location
# ---------------------------------------------------------------------------

def test_get_location_fetches_and_caches(tmp_cache):
    from piframe.weather import get_location
    with patch("requests.get", return_value=_mock_response(LOC_RESP)) as mock_get:
        loc = get_location()
    assert loc["city"] == "London"
    assert loc["approximate"] is False
    assert (tmp_cache / "location.json").exists()


def test_get_location_uses_cache(tmp_cache):
    import config
    cached = {"lat": 48.8, "lon": 2.3, "city": "Paris", "country": "France", "approximate": False}
    config.LOCATION_CACHE.write_text(json.dumps(cached))
    from piframe.weather import get_location
    with patch("requests.get") as mock_get:
        loc = get_location()
        mock_get.assert_not_called()
    assert loc["city"] == "Paris"


def test_get_location_fallback_on_failure(tmp_cache):
    from piframe.weather import get_location
    with patch("requests.get", side_effect=Exception("network down")):
        loc = get_location()
    assert loc["approximate"] is True
    assert loc["lat"] == 51.5


# ---------------------------------------------------------------------------
# get_weather — cache freshness
# ---------------------------------------------------------------------------

def test_get_weather_fetches_and_caches(tmp_cache):
    from piframe.weather import get_weather
    import config
    config.LOCATION_CACHE.write_text(json.dumps({"lat": 51.5, "lon": -0.1, "city": "London", "country": "UK", "approximate": False}))

    with patch("requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_response(FORECAST_RESP),
            _mock_response(AQI_RESP),
        ]
        result = get_weather()

    assert result["stale"] is False
    assert result["current"]["condition"] == "Partly cloudy"
    assert (tmp_cache / "weather.json").exists()


def test_get_weather_returns_fresh_cache(tmp_cache):
    import config
    fresh = {**FORECAST_RESP, "fetched_at": datetime.now(timezone.utc).isoformat(), "stale": False, "current": {}, "location": {}, "hourly_next12": [], "daily": []}
    config.WEATHER_CACHE.write_text(json.dumps(fresh))

    from piframe.weather import get_weather
    with patch("requests.get") as mock_get:
        result = get_weather()
        mock_get.assert_not_called()


def test_get_weather_refetches_stale_cache(tmp_cache):
    import config
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=1800)).isoformat()
    stale = {"fetched_at": old_time, "stale": False, "current": {}, "location": {}, "hourly_next12": [], "daily": []}
    config.WEATHER_CACHE.write_text(json.dumps(stale))
    config.LOCATION_CACHE.write_text(json.dumps({"lat": 51.5, "lon": -0.1, "city": "London", "country": "UK", "approximate": False}))

    from piframe.weather import get_weather
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [_mock_response(FORECAST_RESP), _mock_response(AQI_RESP)]
        result = get_weather()

    assert result["stale"] is False
    assert mock_get.call_count == 2


def test_get_weather_stale_flag_on_http_failure(tmp_cache):
    import config
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=1800)).isoformat()
    last_good = {"fetched_at": old_time, "stale": False, "current": {"temp": 15.0}, "location": {}, "hourly_next12": [], "daily": []}
    config.WEATHER_CACHE.write_text(json.dumps(last_good))
    config.LOCATION_CACHE.write_text(json.dumps({"lat": 51.5, "lon": -0.1, "city": "London", "country": "UK", "approximate": False}))

    from piframe.weather import get_weather
    with patch("requests.get", side_effect=Exception("wifi down")):
        result = get_weather()

    assert result["stale"] is True
    assert result["current"]["temp"] == 15.0


# ---------------------------------------------------------------------------
# AQI label mapping
# ---------------------------------------------------------------------------

def test_aqi_label_good():
    from piframe.weather import _aqi_label
    label, color = _aqi_label(42)
    assert label == "Good"


def test_aqi_label_moderate():
    from piframe.weather import _aqi_label
    label, _ = _aqi_label(75)
    assert label == "Moderate"


def test_aqi_label_none():
    from piframe.weather import _aqi_label
    label, _ = _aqi_label(None)
    assert label == "Unknown"


def test_aqi_label_hazardous():
    from piframe.weather import _aqi_label
    label, _ = _aqi_label(400)
    assert label == "Hazardous"


# ---------------------------------------------------------------------------
# Fahrenheit conversion
# ---------------------------------------------------------------------------

def test_fahrenheit_conversion(tmp_cache):
    import config
    monkeypatch_obj = pytest.MonkeyPatch()
    monkeypatch_obj.setattr(config, "UNITS", "fahrenheit")
    config.LOCATION_CACHE.write_text(json.dumps({"lat": 51.5, "lon": -0.1, "city": "London", "country": "UK", "approximate": False}))

    from piframe.weather import get_weather
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [_mock_response(FORECAST_RESP), _mock_response(AQI_RESP)]
        result = get_weather()

    # 20°C → 68°F
    assert abs(result["current"]["temp"] - 68.0) < 0.1
    monkeypatch_obj.undo()
