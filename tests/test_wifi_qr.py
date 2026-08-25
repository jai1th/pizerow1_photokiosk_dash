import pytest

from piframe import wifi_qr

BS = chr(92)  # single backslash, spelled out to keep escaping unambiguous


# ── WIFI: URI payload ──────────────────────────────────────────────────────

def test_payload_basic():
    assert wifi_qr.wifi_payload("PiFrame-Setup", "frame1234") == \
        "WIFI:T:WPA;S:PiFrame-Setup;P:frame1234;;"


def test_payload_without_password_is_nopass():
    """An empty P: field makes some Android builds reject the join, so the
    field is omitted entirely rather than emitted blank."""
    out = wifi_qr.wifi_payload("OpenNet", "")
    assert out == "WIFI:T:nopass;S:OpenNet;;"
    assert "P:" not in out


def test_payload_hidden_flag():
    assert wifi_qr.wifi_payload("Ghost", "k", hidden=True) == \
        "WIFI:T:WPA;S:Ghost;P:k;H:true;;"


@pytest.mark.parametrize("raw,esc", [
    (";", BS + ";"),
    (",", BS + ","),
    (":", BS + ":"),
    ('"', BS + '"'),
    (BS, BS + BS),
])
def test_payload_escapes_reserved_characters(raw, esc):
    """Unescaped reserved characters truncate the field and the phone joins
    the wrong SSID (or nothing)."""
    assert wifi_qr.wifi_payload("n" + raw, "p" + raw) == \
        "WIFI:T:WPA;S:n" + esc + ";P:p" + esc + ";;"


def test_payload_leaves_ordinary_characters_alone():
    assert wifi_qr.wifi_payload("My Net-2.4G", "s3cr3t!@#$%") == \
        "WIFI:T:WPA;S:My Net-2.4G;P:s3cr3t!@#$%;;"


# ── SVG rendering ──────────────────────────────────────────────────────────

def test_svg_is_self_contained_inline_markup():
    """The kiosk page inlines every asset — ARMv6 WebKit deadlocks on
    subresource loads — so the QR must carry no external references."""
    pytest.importorskip("segno")
    svg = wifi_qr.hotspot_svg("PiFrame-Setup", "frame1234")
    assert svg.startswith("<svg")
    assert "http" not in svg
    assert "<image" not in svg


def test_svg_returns_empty_when_segno_missing(monkeypatch):
    """Degrades to the plain-text credentials shown beside it rather than
    taking down the slideshow render."""
    import builtins
    real_import = builtins.__import__

    def _no_segno(name, *a, **kw):
        if name == "segno":
            raise ImportError("simulated")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_segno)
    assert wifi_qr.svg("anything") == ""
