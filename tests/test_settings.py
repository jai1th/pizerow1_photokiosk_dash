import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "CACHE_DIR",     tmp_path)
    monkeypatch.setattr(config, "WEATHER_CACHE", tmp_path / "weather.json")
    monkeypatch.setattr(config, "LOCATION_CACHE", tmp_path / "location.json")
    monkeypatch.setattr(config, "CALENDAR_CACHE", tmp_path / "calendar.json")
    (tmp_path / "settings.json").write_text("{}")

    from piframe import settings_store
    monkeypatch.setattr(settings_store, "_PATH", tmp_path / "settings.json")

    import app as app_module
    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


class TestApiSettingsDisplay:
    def test_get_includes_layout_and_adaptive(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200
        d = r.get_json()
        assert d["layout"] == "left-bottom"
        assert d["adaptive_color"] is True

    def test_set_valid_layout(self, client):
        r = client.post("/api/settings/display",
                        json={"layout": "right-top"})
        assert r.status_code == 200
        assert r.get_json()["layout"] == "right-top"

        r2 = client.get("/api/settings")
        assert r2.get_json()["layout"] == "right-top"

    def test_set_invalid_layout_returns_400(self, client):
        r = client.post("/api/settings/display",
                        json={"layout": "diagonal"})
        assert r.status_code == 400
        assert "error" in r.get_json()

    def test_set_adaptive_color_false(self, client):
        r = client.post("/api/settings/display",
                        json={"adaptive_color": False})
        assert r.status_code == 200
        r2 = client.get("/api/settings")
        assert r2.get_json()["adaptive_color"] is False

    def test_empty_body_returns_400(self, client):
        r = client.post("/api/settings/display", json={})
        assert r.status_code == 400

    def test_all_four_layouts_valid(self, client):
        for layout in ("left-bottom", "right-bottom", "left-top", "right-top"):
            r = client.post("/api/settings/display", json={"layout": layout})
            assert r.status_code == 200, f"layout {layout!r} should be valid"
