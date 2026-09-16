#!/usr/bin/env python3
"""
Rayo desktop overlay.
Mounts the animated HUD (hud/index.html) as a transparent, click-through
window that sits on the desktop BEHIND your normal windows — the same trick
conky uses (an XWayland desktop-type window), so it works on GNOME/Wayland
where there is no layer-shell.

It also starts the stats bridge (overlay/stats.py) so the HUD shows live data.

Requirements (already present on most GNOME systems):
    python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1
If missing:  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1

Run:     python3 overlay/rayo-overlay.py
Quit:    pkill -f rayo-overlay.py   (and pkill -f overlay/stats.py)
"""
import os, sys, subprocess, signal, atexit, threading, functools
import http.server

# Force the X11 backend so we can use X11 desktop-window hints under XWayland.
os.environ.setdefault("GDK_BACKEND", "x11")
# WebKitGTK's DMABUF renderer frequently fails *silently* on XWayland/hybrid-GPU
# setups — the page renders once then freezes (no animation). Disabling it falls
# back to a renderer that ticks reliably. This is the usual fix for "the overlay
# shows but nothing animates".
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, WebKit2, Gdk, GLib
import cairo
# Register pycairo's types (incl. Region) with GObject-Introspection so
# Gdk.Window.input_shape_combine_region() accepts a cairo.Region.
try:
    gi.require_foreign("cairo")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
HUD_DIR = os.path.join(ROOT, "hud")
HUD = os.path.join(HUD_DIR, "index.html")
STATS = os.path.join(HERE, "stats.py")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # silence request logging
        pass


def start_http_server():
    """Serve hud/ over loopback http so the page can fetch() stats.json.
    (Browsers block fetch() of file:// URLs, which is why file:// showed only
    mock data.) Returns (server, port)."""
    handler = functools.partial(_QuietHandler, directory=HUD_DIR)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)  # 0 = free port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def start_stats_bridge():
    """Keep hud/stats.json fresh. Returns the Popen (or None)."""
    try:
        return subprocess.Popen(
            [sys.executable, STATS, "--interval", "1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[rayo] could not start stats bridge: {e}", file=sys.stderr)
        return None


class Overlay(Gtk.Window):
    def __init__(self, url):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._url = url

        # --- transparency ---
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # --- behave like a desktop widget, not an app window ---
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_below(True)
        self.stick()                      # show on all workspaces
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.set_resizable(False)

        # --- cover the primary monitor ---
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        geo = mon.get_geometry()
        self.move(geo.x, geo.y)
        self.set_default_size(geo.width, geo.height)

        # --- the web view ---
        self.web = WebKit2.WebView()
        s = self.web.get_settings()
        s.set_enable_write_console_messages_to_stdout(False)
        s.set_property("enable-developer-extras", False)
        # allow file:// pages to fetch sibling files (stats.json, theme.json)
        s.set_property("allow-file-access-from-file-urls", True)
        s.set_property("allow-universal-access-from-file-urls", True)
        s.set_property("enable-page-cache", False)
        # transparent webview background so the desktop shows through
        self.web.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        self.add(self.web)
        self.web.load_uri(self._url)

        self.connect("destroy", Gtk.main_quit)
        self.connect("realize", self._on_realize)
        # NOTE: no manual repaint tick. With WEBKIT_DISABLE_DMABUF_RENDERER set,
        # WebKit advances CSS animations on its own timer. Forcing a 30fps
        # queue_draw here was redundant, pegged ~13% CPU, and made the whole
        # screen hitch periodically.

    def _on_realize(self, *_):
        # click-through: give the window an EMPTY input region so every click
        # falls through to whatever is beneath it (the desktop / your icons).
        win = self.get_window()
        if win is None:
            return
        try:
            gi.require_foreign("cairo")
            win.input_shape_combine_region(cairo.Region(), 0, 0)
        except Exception:
            # The pycairo↔GI bridge (python3-gi-cairo) isn't installed, so we
            # can't hand GDK an empty input region. The overlay still shows and
            # works over app windows; only clicks on the bare desktop are caught.
            print("[rayo] click-through disabled — for it, install the bridge:\n"
                  "        sudo apt install python3-gi-cairo\n"
                  "      then restart the overlay.", file=sys.stderr)


def main():
    if not os.path.exists(HUD):
        sys.exit(f"[rayo] HUD not found at {HUD}")

    bridge = start_stats_bridge()
    server, port = start_http_server()
    url = f"http://127.0.0.1:{port}/index.html"

    def cleanup():
        if bridge and bridge.poll() is None:
            bridge.terminate()
        try:
            server.shutdown()
        except Exception:
            pass
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())

    win = Overlay(url)
    win.show_all()
    Gtk.main()
    cleanup()


if __name__ == "__main__":
    main()
