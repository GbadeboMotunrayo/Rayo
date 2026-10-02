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
import os, sys, subprocess, signal, atexit, threading, functools, shutil
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

import json as _json

# --- hub-menu actions (whitelist) -------------------------------------------
# The HUD can ONLY trigger these named actions — never arbitrary commands.
# power-off/reboot/suspend need no password for the active graphical session
# (polkit implicit-active = yes). App launchers fall back through candidates.
ACTIONS = {
    "poweroff": [["systemctl", "poweroff"]],
    "reboot":   [["systemctl", "reboot"]],
    "suspend":  [["systemctl", "suspend"]],
    "lock":     [["loginctl", "lock-session"], ["gnome-screensaver-command", "-l"]],
    "logout":   [["gnome-session-quit", "--logout", "--no-prompt"]],
    "files":    [["nautilus", "--new-window"], ["xdg-open", os.path.expanduser("~")]],
    "terminal": [["ptyxis"], ["kgx"], ["gnome-terminal"], ["xterm"]],
    "web":      [["firefox"], ["xdg-open", "https://duckduckgo.com"]],
    "settings": [["gnome-control-center"]],
    "displays": [["gnome-control-center", "display"]],
}


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves hud/ to the overlay only. Hardened because the page can call the hub's power actions:
      - Host header must be 127.0.0.1:<port> or localhost:<port>  (blocks DNS-rebinding from web pages)
      - GET/HEAD only; no directory listings; no dotfiles; nothing outside hud/ (symlinks included)
      - security headers, including a CSP that forbids every script except our own files"""
    allowed_hosts = set()                     # filled in once the port is known
    CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "font-src 'self' data:; connect-src 'self'; media-src 'none'; object-src 'none'; frame-src 'none'; "
           "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    def log_message(self, *a):  # silence request logging
        pass

    def _allowed(self):
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in self.allowed_hosts:
            self.send_error(421, "Misdirected Request")
            return False
        return True

    def do_GET(self):
        if self._allowed():
            super().do_GET()

    def do_HEAD(self):
        if self._allowed():
            super().do_HEAD()

    def _refuse(self):
        self.send_error(405, "Method Not Allowed")

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    def list_directory(self, path):          # never expose a file listing
        self.send_error(404, "Not Found")
        return None

    def translate_path(self, path):
        real = os.path.realpath(super().translate_path(path))
        root = os.path.realpath(HUD_DIR)
        parts = os.path.relpath(real, root).split(os.sep)
        if real != root and (not real.startswith(root + os.sep) or any(p.startswith(".") for p in parts)):
            return os.path.join(root, "__forbidden__")          # resolves to a 404
        return real

    def end_headers(self):
        # Never let the embedded browser reuse an old copy. The server runs on a
        # fixed port (so theme choice persists), which made WebKit's disk cache
        # keep serving pre-update scripts across restarts.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", self.CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        super().end_headers()


def start_http_server():
    """Serve hud/ over loopback http so the page can fetch() stats.json + theme
    files. Prefer a FIXED port so the page's origin is stable — that lets the
    chosen theme (saved in localStorage) survive overlay restarts. Fall back to
    a random free port if the fixed one is busy. Returns (server, port)."""
    handler = functools.partial(_QuietHandler, directory=HUD_DIR)
    srv = None
    for port in (8791, 0):
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    port = srv.server_address[1]
    _QuietHandler.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


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
        self._paused = False
        self._voice_proc = None

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
        # NOTE: not WindowTypeHint.DESKTOP — the WM pins DESKTOP windows to the
        # PRIMARY monitor's origin, so the HUD couldn't be placed on the TV.
        # A normal, undecorated, kept-below, click-through window can live on
        # any monitor and still acts as a backdrop.
        self.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.set_resizable(False)

        # --- choose which monitor the HUD lives on ---
        # Prefer an EXTERNAL screen (the TV) as the ambient backdrop; fall back
        # to the built-in panel when nothing else is connected. Placement is by
        # geometry (reliable now that displays are at integer scale 1.0).
        disp = Gdk.Display.get_default()
        target = None
        for i in range(disp.get_n_monitors()):
            m = disp.get_monitor(i)
            if not m.is_primary():
                target = m
                break
        if target is None:
            target = disp.get_primary_monitor() or disp.get_monitor(0)
        g = target.get_geometry()
        self._geo = (g.x, g.y, g.width, g.height)
        self.move(g.x, g.y)
        self.set_default_size(g.width, g.height)
        self.resize(g.width, g.height)

        # --- the web view (with a JS→system command bridge) ---
        # No HTTP disk cache: files come from loopback, so caching buys nothing
        # and a stale cache hides updates. (localStorage — theme choice — is
        # separate and still persists.)
        WebKit2.WebContext.get_default().set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        # The HUD's hub is interactive: clicking it opens menus whose actions
        # (shutdown, sleep, launch apps…) are sent from the page to here via
        # window.webkit.messageHandlers.rayo.postMessage(...). We run them.
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("rayo")
        ucm.connect("script-message-received::rayo", self._on_hud_message)
        self.web = WebKit2.WebView.new_with_user_content_manager(ucm)
        s = self.web.get_settings()
        s.set_enable_write_console_messages_to_stdout(False)
        s.set_property("enable-developer-extras", False)
        # The HUD is served over http://127.0.0.1, so file:// relaxations are not needed: keep them off.
        s.set_property("allow-file-access-from-file-urls", False)
        s.set_property("allow-universal-access-from-file-urls", False)
        s.set_property("enable-page-cache", False)
        s.set_property("javascript-can-open-windows-automatically", False)
        # Lock the window to our own origin: the page can call power actions, so it must never be steered elsewhere.
        self._origin = self._url.rsplit("/", 1)[0]
        self.web.connect("decide-policy", self._on_policy)
        self.web.connect("create", lambda *a: None)                          # no pop-up windows
        self.web.connect("permission-request", lambda w, req: (req.deny(), True)[1])   # no mic/camera/location for the page
        # transparent webview background so the desktop shows through
        self.web.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        self.add(self.web)
        self.web.load_uri(self._url)

        self.connect("destroy", Gtk.main_quit)
        self.connect("realize", self._on_realize)
        self.connect("map", self._place)
        # NOTE: no manual repaint tick. With WEBKIT_DISABLE_DMABUF_RENDERER set,
        # WebKit advances CSS animations on its own timer. Forcing a 30fps
        # queue_draw here was redundant, pegged ~13% CPU, and made the whole
        # screen hitch periodically.

        # --- pause animation when the HUD is fully covered by a window ---
        # The HUD is a backdrop: when you maximise/stack a window over it you
        # can't see it, so there's no point spending CPU spinning rings nobody
        # can see (that's what kept the fan up). X11/XWayland delivers a
        # VisibilityNotify when the window becomes fully obscured or exposed;
        # we freeze the page on obscure and un-freeze on expose. Freezing takes
        # the WebKit process to ~0% CPU.
        self.add_events(Gdk.EventMask.VISIBILITY_NOTIFY_MASK)
        self.connect("visibility-notify-event", self._on_visibility)

    def _on_visibility(self, _w, event):
        # FULLY_OBSCURED → nothing of the HUD is visible → freeze it.
        # UNOBSCURED / PARTIALLY_OBSCURED → some of it shows → keep it alive.
        try:
            obscured = (event.state == Gdk.VisibilityState.FULLY_OBSCURED)
        except Exception:
            obscured = False
        self._set_paused(obscured)
        return False

    def _set_paused(self, paused):
        if paused == self._paused:
            return
        self._paused = paused
        # Toggle the .rayo-idle class the stylesheet uses to pause every
        # animation (animation-play-state:paused). WebKit then stops
        # re-compositing and the process idles at ~0% CPU.
        js = ("document.documentElement.classList.%s('rayo-idle')"
              % ("add" if paused else "remove"))
        try:
            self.web.run_javascript(js, None, None, None)
        except Exception:
            pass

    def _on_policy(self, web, decision, dtype):
        """Only our own origin may be loaded; links, redirects and new windows elsewhere are refused."""
        if dtype in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri() or ""
            if not (uri == "about:blank" or uri.startswith(self._origin + "/")):
                print(f"[rayo] blocked navigation to {uri[:80]}", file=sys.stderr)
                decision.ignore()
                return True
        return False

    def _on_hud_message(self, _ucm, js_result):
        """Receive {action: ...} from the HUD and run the matching whitelisted
        command. Anything not in ACTIONS (or the DND toggle) is ignored."""
        if not (self.web.get_uri() or "").startswith(self._origin + "/"):    # only our own page may drive the hub
            return
        try:
            val = js_result.get_js_value()
            data = _json.loads(val.to_string())
            action = data.get("action", "")
        except Exception as e:
            print(f"[rayo] bad hud message: {e}", file=sys.stderr)
            return
        if action == "dnd":
            self._toggle_dnd()
            return
        if action == "voice":
            self._toggle_voice()
            return
        candidates = ACTIONS.get(action)
        if not candidates:
            return
        for argv in candidates:
            if shutil.which(argv[0]) is None:
                continue
            try:
                subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                print(f"[rayo] action: {action} -> {' '.join(argv)}")
                return
            except Exception as e:
                print(f"[rayo] action {action} failed: {e}", file=sys.stderr)
        print(f"[rayo] action {action}: no runnable command found", file=sys.stderr)

    def _toggle_voice(self):
        """Toggle the wake-word listener (voice.sh --wake). Off by default, so
        it only listens when you ask. Its stdout "@event" lines are streamed
        into the HUD so the reactor shows armed / listening / heard / errors."""
        p = getattr(self, "_voice_proc", None)
        if p and p.poll() is None:
            self._kill_voice()
            self._voice_event("off", "")
            return
        try:
            self._voice_proc = subprocess.Popen(
                [os.path.join(HERE, "voice.sh"), "--wake"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                bufsize=1, start_new_session=True)
        except Exception as e:
            self._voice_event("error", f"voice failed to start: {e}")
            return
        if not getattr(self, "_voice_atexit", False):
            atexit.register(self._kill_voice)
            self._voice_atexit = True
        self._voice_event("starting", "")
        threading.Thread(target=self._pump_voice, args=(self._voice_proc,), daemon=True).start()
        print("[rayo] voice wake mode ON")

    def _pump_voice(self, proc):
        """Background thread: forward the listener's @events to the HUD."""
        saw_off = False
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("@"):
                continue
            kind, _, payload = line[1:].partition(" ")
            saw_off = saw_off or kind == "off"
            self._voice_event(kind, payload)
        if not saw_off:                       # died without saying goodbye
            self._voice_event("off", "")

    def _voice_event(self, kind, payload):
        """Thread-safe: hand one voice event to the page on the GTK main loop."""
        js = ("window.RayoVoice && window.RayoVoice.on(%s, %s)"
              % (_json.dumps(kind), _json.dumps(payload)))
        def _run():
            try:
                self.web.run_javascript(js, None, None, None)
            except Exception:
                pass
            return False
        GLib.idle_add(_run)

    def _kill_voice(self):
        p = getattr(self, "_voice_proc", None)
        if p and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                try: p.terminate()
                except Exception: pass
        self._voice_proc = None

    def _toggle_dnd(self):
        """Toggle Focus/Do-Not-Disturb (GNOME 'show-banners')."""
        try:
            cur = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
                text=True).strip()
            new = "false" if cur == "true" else "true"
            subprocess.run(["gsettings", "set", "org.gnome.desktop.notifications",
                            "show-banners", new], check=False)
            print(f"[rayo] focus/DND -> banners {new}")
        except Exception as e:
            print(f"[rayo] dnd toggle failed: {e}", file=sys.stderr)

    def _place(self, *_):
        # Re-assert exact position+size on its monitor (some WMs nudge a new
        # undecorated window; this pins it to the chosen screen).
        x, y, w, h = self._geo
        try:
            self.move(x, y)
            self.resize(w, h)
        except Exception as e:
            print(f"[rayo] could not place overlay: {e}", file=sys.stderr)

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
