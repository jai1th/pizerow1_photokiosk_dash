"""Tests for the pure-logic parts of deploy/piframe-netctl.

The script is deliberately extensionless and hyphenated (it is a system
command, not an importable module), so it is loaded by path.
"""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "deploy" / "piframe-netctl"


@pytest.fixture(scope="module")
def netctl():
    spec = importlib.util.spec_from_loader(
        "piframe_netctl",
        importlib.machinery.SourceFileLoader("piframe_netctl", str(_SRC)),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── scan parsing ───────────────────────────────────────────────────────────

SCAN_SAMPLE = """
BSS aa:bb:cc:dd:ee:01(on wlan0)
	signal: -42.00 dBm
	SSID: HomeNet
BSS aa:bb:cc:dd:ee:02(on wlan0)
	signal: -80.00 dBm
	SSID: FarAway
BSS aa:bb:cc:dd:ee:03(on wlan0)
	signal: -55.00 dBm
	SSID: HomeNet
BSS aa:bb:cc:dd:ee:04(on wlan0)
	signal: -60.00 dBm
	SSID:
"""


def test_parse_scan_ranks_by_signal(netctl):
    nets = netctl.parse_scan(SCAN_SAMPLE)
    assert [n["ssid"] for n in nets] == ["HomeNet", "FarAway"]


def test_parse_scan_dedupes_to_strongest_bss(netctl):
    """One SSID often appears as several BSSes; the join form wants one row."""
    nets = netctl.parse_scan(SCAN_SAMPLE)
    home = [n for n in nets if n["ssid"] == "HomeNet"]
    assert len(home) == 1
    assert home[0]["signal"] == -42.0


def test_parse_scan_drops_hidden_networks(netctl):
    assert all(n["ssid"] for n in netctl.parse_scan(SCAN_SAMPLE))


def test_parse_scan_handles_empty_input(netctl):
    assert netctl.parse_scan("") == []


def test_parse_scan_survives_malformed_signal(netctl):
    out = "BSS aa:bb:cc:dd:ee:01(on wlan0)\n\tsignal: garbage\n\tSSID: Weird\n"
    assert netctl.parse_scan(out) == [{"ssid": "Weird", "signal": -99.0}]


def test_parse_scan_keeps_ssid_with_spaces(netctl):
    out = "BSS aa:bb:cc:dd:ee:01(on wlan0)\n\tsignal: -30.00 dBm\n\tSSID: My Net 2.4G\n"
    assert netctl.parse_scan(out)[0]["ssid"] == "My Net 2.4G"


# ── wpa_supplicant block ───────────────────────────────────────────────────

BS = chr(92)


def test_wpa_block_quotes_and_escapes(netctl, monkeypatch):
    """Fallback path, used when wpa_passphrase can't hash the input.

    An unescaped quote inside an SSID would terminate the string early and
    wpa_supplicant would silently associate with the wrong network, or none.
    """
    monkeypatch.setattr(netctl, "run", lambda *a, **k: (1, ""))
    block = netctl.wpa_block('we"ird', "pa" + BS + "ss")
    assert 'ssid="we' + BS + '"ird"' in block
    assert 'psk="pa' + BS + BS + 'ss"' in block


def test_wpa_block_prefers_hashed_psk(netctl, monkeypatch):
    """The hashed form keeps the plaintext passphrase out of the config."""
    hashed = 'network={\n\tssid="Home"\n\t#psk="secret"\n\tpsk=abc123\n}'
    monkeypatch.setattr(netctl, "run", lambda *a, **k: (0, hashed))
    block = netctl.wpa_block("Home", "secret")
    assert "psk=abc123" in block
    assert "secret" not in block, "plaintext passphrase leaked into config"


# ── defaults sanity ────────────────────────────────────────────────────────

def test_defaults_password_meets_wpa2_minimum(netctl):
    """hostapd refuses to start WPA2 with a passphrase under 8 characters."""
    assert len(netctl.DEFAULTS["hotspot_password"]) >= 8
