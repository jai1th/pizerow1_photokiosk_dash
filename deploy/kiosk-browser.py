#!/usr/bin/env python3
"""PiFrame kiosk browser — GTK + WebKit2, full-screen, no chrome.

Do NOT call ctx.set_cache_model() or create a standalone WebKit2.Settings()
object — those trigger "Invalid value for lock" on BCM2835/ARMv6 at WebKit
subprocess startup.

Do NOT pass vt1 to xinit — it causes the same lock failure in the
WebKitNetworkProcess, breaking subsequent fetch() calls in the page.
"""
import gi, os, signal, sys
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib, Gdk

URL = os.environ.get('PIFRAME_URL', 'http://127.0.0.1:5000/')


def _screen_size():
    """Real X screen geometry.

    xinit starts no window manager, so _NET_WM_STATE_FULLSCREEN goes unhandled
    and win.fullscreen() would silently do nothing. A hardcoded 1920x1080
    window then overflows a smaller framebuffer: the page still reports
    innerWidth/innerHeight as 1920x1080, slideshow.js computes scale 1.0, and
    the bottom/right of the layout land off-screen behind the panel's letterbox
    bars. Size to the actual screen and let slideshow.js scale its fixed
    1920x1080 canvas down to fit.
    """
    disp = Gdk.Display.get_default()
    try:
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        geo = mon.get_geometry()
        if geo.width > 0 and geo.height > 0:
            return geo.width, geo.height
    except Exception as e:
        print(f'kiosk: monitor geometry warning: {e}', flush=True)
    scr = Gdk.Screen.get_default()
    return scr.get_width(), scr.get_height()


_SW, _SH = _screen_size()
print(f'kiosk: screen {_SW}x{_SH}', flush=True)

# Paint everything black. The slideshow refreshes itself with a full-page
# navigation (the only reliable load path on this ARMv6 WebKit); during that
# navigation the view briefly shows its base background. Default is white,
# which flashed every ~30s against the otherwise-black UI. Black window +
# black WebView base = the reload is invisible.
try:
    _css = Gtk.CssProvider()
    _css.load_from_data(b'window, * { background-color: #000; }')
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), _css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
except Exception as e:
    print(f'kiosk: window bg warning: {e}', flush=True)

win = Gtk.Window()
win.set_title('PiFrame')
win.set_default_size(_SW, _SH)
win.set_decorated(False)
win.connect('destroy', Gtk.main_quit)
signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())

_view = None

def _make_view():
    global _view
    ctx = WebKit2.WebContext.new()
    v = WebKit2.WebView.new_with_context(ctx)
    try:
        v.set_background_color(Gdk.RGBA(0.0, 0.0, 0.0, 1.0))  # black, not white
    except Exception as e:
        print(f'kiosk: webview bg warning: {e}', flush=True)
    v.connect('load-changed', _on_load_changed)
    v.connect('load-failed', _on_load_failed)
    v.connect('web-process-terminated', _on_web_process_terminated)
    _view = v
    return v

def _set_cursor(window):
    try:
        blank = Gdk.Cursor.new_for_display(window.get_display(), Gdk.CursorType.BLANK_CURSOR)
        window.get_window().set_cursor(blank)
    except Exception as e:
        print(f'kiosk: cursor warning: {e}', flush=True)

_load_failures = 0
_MAX_FAILURES  = 5

def _on_load_changed(v, event):
    global _load_failures
    if event == WebKit2.LoadEvent.COMMITTED:
        _load_failures = 0

def _on_load_failed(v, event, uri, err):
    global _load_failures
    _load_failures += 1
    print(f'kiosk: load failed ({_load_failures}/{_MAX_FAILURES}): {err.message}', flush=True)
    if _load_failures >= _MAX_FAILURES:
        print('kiosk: too many failures — exiting for systemd restart', flush=True)
        sys.exit(1)
    GLib.timeout_add_seconds(10, lambda: (_view.load_uri(URL), False)[1])
    return True

def _on_web_process_terminated(v, reason):
    """Replace the dead WebView with a fresh one — don't kill X."""
    print(f'kiosk: web-process terminated ({reason.value_name}) — replacing WebView in 5s', flush=True)
    old_view = v
    def _respawn():
        new_v = _make_view()
        win.remove(old_view)
        win.add(new_v)
        new_v.show()
        _set_cursor(win)
        print(f'kiosk: reloading {URL}', flush=True)
        new_v.load_uri(URL)
        return False
    GLib.timeout_add_seconds(5, _respawn)

# Initial setup
view = _make_view()
win.add(view)
win.show_all()
win.move(0, 0)
win.resize(_SW, _SH)
_set_cursor(win)

print(f'kiosk: loading {URL}', flush=True)
view.load_uri(URL)
Gtk.main()
print('kiosk: exiting', flush=True)
