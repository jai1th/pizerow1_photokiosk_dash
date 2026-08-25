"""WiFi join QR — encodes hotspot credentials as an inline SVG QR code.

The kiosk page inlines every asset (ARMv6 WebKit deadlocks on subresource
loads, see routes_pages._INLINE_CSS), so the QR is emitted as an inline
<svg> string dropped straight into the template — never served from an
endpoint and never referenced via <img src>.
"""
import logging

log = logging.getLogger(__name__)

# Characters that must be backslash-escaped inside a WIFI: URI field.
_SPECIALS = r'\;,:"'


def _esc(value: str) -> str:
    return "".join("\\" + c if c in _SPECIALS else c for c in value)


def wifi_payload(ssid: str, password: str = "", hidden: bool = False) -> str:
    """Build the WIFI: URI that phone cameras parse as a join request.

    Format:  WIFI:T:WPA;S:<ssid>;P:<password>;H:true;;
    An empty password yields T:nopass and omits the P field entirely —
    a P: field with an empty value makes some Android builds fail the join.
    """
    parts = ["WIFI:T:" + ("WPA" if password else "nopass"), "S:" + _esc(ssid)]
    if password:
        parts.append("P:" + _esc(password))
    if hidden:
        parts.append("H:true")
    return ";".join(parts) + ";;"


def svg(data: str, scale: int = 7, border: int = 3,
        dark: str = "#0c0b10", light: str = "#ffffff") -> str:
    """Render `data` as an inline <svg> QR, or "" if segno is unavailable.

    Returns "" rather than raising: a missing QR should degrade to the
    plain-text credentials the setup panel shows alongside it, not take
    down the whole slideshow render.

    error='m' (~15% recovery) is deliberate — 'l' is fragile against a
    phone camera angled at a glossy panel, and 'q'/'h' inflate the module
    count enough to hurt scanning at typical frame-viewing distance.
    """
    try:
        import segno
    except ImportError:
        log.warning("segno not installed — wifi QR unavailable")
        return ""
    try:
        return segno.make(data, error="m").svg_inline(
            scale=scale, border=border, dark=dark, light=light)
    except Exception as exc:
        log.warning("wifi QR render failed: %s", exc)
        return ""


def hotspot_svg(ssid: str, password: str = "", **kw) -> str:
    """Convenience: payload + render in one call."""
    return svg(wifi_payload(ssid, password), **kw)
