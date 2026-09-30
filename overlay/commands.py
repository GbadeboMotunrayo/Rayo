"""
Rayo voice commands: turn one spoken sentence into one action.

resolve(text) is pure (no side effects) and returns a plan:
    {"kind": ..., "arg": ..., "msg": "what Rayo will say it did"}
execute(plan) carries it out and returns the final message. Keeping them
apart means every phrase can be tested without a microphone.

What Rayo understands (wake word first, e.g. "Rayo, open claude"):
  open <any installed app>        open claude · open obs · launch calculator
  open <place>                    open documents · open downloads · open desktop
  open <folder name>              open tech · open the carpadi folder
  open <folder> and <folder>      open downloads and tech
  open document/file <name>       open document resume
  search for <anything>           search for weather in lagos
  go to <site>                    open youtube · go to github
  volume up / down · mute · unmute
  play / pause · next song · previous song
  what time is it · what's the date · battery · temperature
  next theme · bench mode · exit bench
  settings · wifi / bluetooth / sound / display settings
  lock · sleep · focus · help
Power actions (shutdown/restart) are refused on purpose.
"""
import os, re, time, glob, shutil, difflib, subprocess, urllib.parse

HOME = os.path.expanduser("~")


def _user_dir(key, fallback):
    try:
        p = subprocess.run(["xdg-user-dir", key], capture_output=True, text=True, timeout=2).stdout.strip()
        return p if p and os.path.isdir(p) else os.path.join(HOME, fallback)
    except Exception:
        return os.path.join(HOME, fallback)


DOCUMENTS = _user_dir("DOCUMENTS", "Documents")
DOWNLOADS = _user_dir("DOWNLOAD", "Downloads")
DESKTOP = _user_dir("DESKTOP", "Desktop")
PICTURES = _user_dir("PICTURES", "Pictures")
MUSIC = _user_dir("MUSIC", "Music")
VIDEOS = _user_dir("VIDEOS", "Videos")

PLACES = {
    "documents": DOCUMENTS, "downloads": DOWNLOADS, "download": DOWNLOADS,
    "desktop": DESKTOP, "pictures": PICTURES, "photos": PICTURES, "music": MUSIC,
    "videos": VIDEOS, "home": HOME, "home folder": HOME,
}
SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "github": "https://github.com", "gmail": "https://mail.google.com",
    "chatgpt": "https://chatgpt.com", "chat gpt": "https://chatgpt.com", "chat g p t": "https://chatgpt.com",
    "whatsapp": "https://web.whatsapp.com", "whats app": "https://web.whatsapp.com",
    "what's app": "https://web.whatsapp.com", "claude dot ai": "https://claude.ai",
    "mail": "https://mail.google.com", "email": "https://mail.google.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com",
    "netflix": "https://www.netflix.com", "twitter": "https://x.com", "x": "https://x.com",
    "linkedin": "https://www.linkedin.com", "instagram": "https://www.instagram.com",
}
SETTINGS_PANELS = {
    "wifi": "wifi", "wi fi": "wifi", "wireless": "wifi", "network": "network",
    "bluetooth": "bluetooth", "sound": "sound", "audio": "sound", "display": "display",
    "displays": "display", "monitor": "display", "power": "power", "battery": "power",
    "keyboard": "keyboard", "mouse": "mouse", "background": "background", "wallpaper": "background",
    "notifications": "notifications", "privacy": "privacy", "apps": "applications",
}
TERMINALS = [["ptyxis"], ["kgx"], ["gnome-terminal"], ["xterm"]]
DOC_EXT = (".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rtf", ".xls", ".xlsx", ".ods",
           ".csv", ".ppt", ".pptx", ".odp", ".epub", ".png", ".jpg", ".jpeg", ".mp4", ".mp3")
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", "dist", "build",
             "target", "vendor", ".git", "snap"}
FILLER = ("please ", "can you ", "could you ", "would you ", "rayo ", "ray oh ", "hey ", "okay ", "ok ")


# ---- matching helpers --------------------------------------------------------
def norm(s):
    s = s.lower()
    s = re.sub(r"[-_.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def score(query, name):
    """Similarity 0..1, tolerant of the recogniser splitting or joining words
    ('car paddy' ~ 'Carpadi', 'hero hud' ~ 'herohud')."""
    q, n = norm(query), norm(name)
    if not q or not n:
        return 0.0
    qs, ns = q.replace(" ", ""), n.replace(" ", "")
    if q == n or qs == ns:
        return 1.0
    return max(difflib.SequenceMatcher(None, q, n).ratio(),
               difflib.SequenceMatcher(None, qs, ns).ratio())


def best(query, entries, cutoff):
    """entries: [(name, value, depth)] → value of the best match or None."""
    top, top_key = None, (cutoff, 0)
    for name, value, depth in entries:
        s = score(query, name)
        key = (s, -depth)
        if s >= cutoff and key > top_key:
            top, top_key = value, key
    return top


# ---- indexes (built lazily, cached 10 min) -----------------------------------
_cache = {}


def _cached(key, build, ttl=600):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = build()
    _cache[key] = (time.time(), val)
    return val


def _walk(root, max_depth, want_files=False):
    out = []
    if not os.path.isdir(root):
        return out
    base = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.count(os.sep) - base
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        if depth >= max_depth:
            dirnames[:] = []
        if want_files:
            out += [(os.path.splitext(f)[0], os.path.join(dirpath, f), depth)
                    for f in filenames if f.lower().endswith(DOC_EXT) and not f.startswith(".")]
        else:
            out += [(d, os.path.join(dirpath, d), depth + 1) for d in dirnames]
    return out


def folder_index():
    def build():
        entries = _walk(HOME, 1)
        for root, depth in ((DESKTOP, 3), (DOCUMENTS, 3), (DOWNLOADS, 2), (PICTURES, 2),
                            (MUSIC, 1), (VIDEOS, 1)):
            entries += _walk(root, depth)
        return entries
    return _cached("folders", build)


def file_index():
    def build():
        entries = []
        for root, depth in ((DOCUMENTS, 3), (DESKTOP, 3), (DOWNLOADS, 2)):
            entries += _walk(root, depth, want_files=True)
        return entries
    return _cached("files", build)


APP_DIRS = ["/usr/share/applications", "/usr/local/share/applications",
            "/var/lib/snapd/desktop/applications", "/var/lib/flatpak/exports/share/applications",
            os.path.join(HOME, ".local/share/flatpak/exports/share/applications"),
            os.path.join(HOME, ".local/share/applications")]      # last = user overrides win


def _read_desktop(path):
    info, in_entry = {}, False
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    in_entry = line == "[Desktop Entry]"
                    continue
                if in_entry and "=" in line:
                    k, v = line.split("=", 1)
                    info.setdefault(k.strip(), v.strip())
    except OSError:
        pass
    return info


def app_index():
    """[(name, desktop_path, 0)] for launchable, visible applications."""
    def build():
        apps = {}
        for d in APP_DIRS:
            for path in glob.glob(os.path.join(d, "*.desktop")):
                i = _read_desktop(path)
                if i.get("Type") != "Application" or i.get("NoDisplay") == "true" or i.get("Hidden") == "true":
                    continue
                name = i.get("Name")
                if name:
                    apps[name.lower()] = (name, path, 0)
        return list(apps.values())
    return _cached("apps", build)


def default_browser():
    try:
        did = subprocess.run(["xdg-settings", "get", "default-web-browser"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        did = ""
    for name, path, _ in app_index():
        if did and os.path.basename(path) == did:
            return ("app", path, name)
    return ("argv", [["firefox"], ["xdg-open", "https://duckduckgo.com"]], "browser")


def browser_options():
    """[(label, desktop_path)] of installed browsers, default browser first."""
    def build():
        seen, out = set(), []
        for d in APP_DIRS:
            for path in sorted(glob.glob(os.path.join(d, "*.desktop"))):
                i = _read_desktop(path)
                if i.get("Type") != "Application" or i.get("NoDisplay") == "true":
                    continue
                if "WebBrowser" not in i.get("Categories", ""):
                    continue
                label = re.sub(r"\s*(web )?browser$", "", i.get("Name", "").strip(), flags=re.I).lower()
                if label and label not in seen:
                    seen.add(label)
                    out.append((label, path))
        return out
    opts = _cached("browsers", build)
    d = default_browser()
    return sorted(opts, key=lambda o: o[1] != d[1]) if d[0] == "app" else opts


def _choices(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


# ---- resolve: sentence → plan -------------------------------------------------
def plan(kind, arg=None, msg=""):
    return {"kind": kind, "arg": arg, "msg": msg}


def clean(text):
    t = " " + norm(text) + " "
    for f in FILLER:
        t = t.replace(" " + f, " ")
    t = re.sub(r"\b(for me|thank you|thanks)\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _strip_articles(t):
    return re.sub(r"^(the|my|a|an)\s+", "", t).strip()


def _open_target(t, verb="open"):
    """Resolve what follows 'open' (or a bare noun)."""
    t = _strip_articles(t)
    if not t:
        return plan("none", msg="open what?")
    # missing detail -> ask a follow-up question
    if t in ("document", "file", "document file"):
        return plan("ask", {"expect": "document"}, "which document?")
    if t == "folder":
        return plan("ask", {"expect": "folder"}, "which folder?")
    if t in ("app", "application", "program"):
        return plan("ask", {"expect": "app"}, "which app?")
    if t in ("browser", "browsers", "web browser") and verb in ("launch", "start", "run"):
        opts = browser_options()
        if len(opts) > 1:
            return plan("ask", {"expect": "browser", "options": opts},
                        "which browser? " + _choices([l for l, _ in opts]))
        if opts:
            return plan("app", opts[0][1], f"opening {opts[0][0]}")
    # explicit folder(s): "folder tech", "the tech folder", "downloads and tech folders"
    m = re.match(r"^folders?\s+(?:called|named)?\s*(.+)$", t) or re.match(r"^(.+?)\s+folders?$", t)
    if m:
        return _folders(m.group(1))
    # explicit document/file: "document resume", "file budget"
    m = re.match(r"^(?:document|file)s?\s+(?:called|named)?\s*(.+)$", t)
    if m:
        path = best(m.group(1), file_index(), 0.8)
        return plan("open", path, f"opening {os.path.basename(path)}") if path else \
            plan("none", msg=f"no document like “{m.group(1)}”")
    if t in PLACES:
        return plan("open", PLACES[t], f"opening {t}")
    if t in ("browser", "internet", "web", "the internet", "web browser"):
        return plan(*default_browser()[:2], msg="opening browser")
    if t in ("files", "file manager", "file explorer", "explorer"):
        return plan("argv", [["nautilus", "--new-window"], ["xdg-open", HOME]], "opening files")
    if t in ("terminal", "console", "shell", "command line"):
        return plan("argv", TERMINALS, "opening terminal")
    if t in ("settings", "system settings", "preferences"):
        return plan("argv", [["gnome-control-center"]], "opening settings")
    m = re.match(r"^(.+?)\s+settings$", t)
    if m and m.group(1) in SETTINGS_PANELS:
        return plan("argv", [["gnome-control-center", SETTINGS_PANELS[m.group(1)]]], f"opening {m.group(1)} settings")
    apps = app_index()
    exact = [(n, p, d) for n, p, d in apps if norm(n) == norm(t) or
             (len(t) >= 3 and norm(n).startswith(norm(t) + " "))]
    if exact:
        return plan("app", exact[0][1], f"opening {exact[0][0].lower()}")
    if t in SITES:
        host = urllib.parse.urlparse(SITES[t]).hostname.replace("www.", "")
        return plan("url", SITES[t], f"opening {host}")
    path = best(t, [(n, p, d) for n, p, d in apps], 0.82)
    if path:
        return plan("app", path, f"opening {_app_name(path)}")
    if " and " in t:
        multi = _folders(t)
        if multi["kind"] != "none":
            return multi
    folder = best(t, folder_index(), 0.75)
    if folder:
        return plan("open", folder, f"opening {os.path.basename(folder)}")
    return plan("none", msg=f"couldn't find “{t}”")


def _folders(spec):
    """One or more folders: 'tech', 'downloads and tech'."""
    found, missing = [], []
    for part in re.split(r"\s+and\s+|,\s*", spec):
        part = _strip_articles(part.strip())
        if not part:
            continue
        path = PLACES.get(part) or best(part, folder_index(), 0.72)
        (found if path else missing).append(path or part)
    if not found:
        return plan("none", msg=f"no folder like “{spec}”")
    names = " + ".join(os.path.basename(p) or p for p in found)
    note = f" (couldn't find {', '.join(missing)})" if missing else ""
    return plan("open_many", found, f"opening {names}{note}")


def _app_name(path):
    for n, p, _ in app_index():
        if p == path:
            return n.lower()
    return os.path.basename(path)


def resolve(text):
    t = clean(text)
    if not t:
        return plan("none", msg="didn't catch that")
    if re.search(r"\b(shut ?down|power off|restart|reboot|turn off the computer)\b", t):
        return plan("refuse", msg="power stays on the hub (safety)")
    if re.search(r"\b(help|what can you do|commands)\b", t):
        return plan("say", msg="try: open claude · open downloads · search for …")
    if re.search(r"\bwhat( i|')?s? the time\b|\bwhat time\b|\bthe time\b", t):
        return plan("say", msg="it's " + time.strftime("%-I:%M %p").lower())
    if re.search(r"\b(what( i|')?s? the date|what day|today'?s date|the date)\b", t):
        return plan("say", msg=time.strftime("%A, %B %-d").lower())
    if re.search(r"\bbattery\b", t) and not t.endswith("settings"):
        return plan("battery")
    if re.search(r"\b(temperature|how hot|thermals?)\b", t):
        return plan("temp")
    # HUD
    if re.search(r"\b(exit|close|leave|stop) (the )?bench\b", t):
        return plan("hud", "bench_off", "closing bench")
    if re.search(r"\bbench\b", t):
        return plan("hud", "bench", "bench mode")
    if re.search(r"\b(next|change|switch|another|new) (the )?themes?\b|^themes?$", t):
        return plan("hud", "theme", "switching theme")
    # volume & media
    if re.search(r"\b(volume up|louder|turn (it )?up|increase (the )?volume)\b", t):
        return plan("volume", "+", "volume up")
    if re.search(r"\b(volume down|quieter|softer|turn (it )?down|decrease (the )?volume|lower (the )?volume)\b", t):
        return plan("volume", "-", "volume down")
    if re.search(r"\b(un ?mute|on mute|sound on)\b", t):
        return plan("volume", "unmute", "unmuted")
    if re.search(r"\b(mute|silence the sound|sound off)\b", t):
        return plan("volume", "mute", "muted")
    if re.search(r"\b(next (song|track)|skip( this)?( song| track)?)\b", t):
        return plan("media", "Next", "next track")
    if re.search(r"\b(previous|last) (song|track)\b", t):
        return plan("media", "Previous", "previous track")
    if re.search(r"^(play|pause|resume|stop)( (the )?(music|song|video|it))?$", t):
        return plan("media", "PlayPause", "play / pause")
    # search the web
    if re.fullmatch(r"(search|google|look up)( for)?( something)?", t):
        return plan("ask", {"expect": "search"}, "search for what?")
    m = re.match(r"^(?:search|google|look up|find online)(?: for| up)?\s+(.+)$", t)
    if m:
        q = m.group(1)
        return plan("url", "https://www.google.com/search?q=" + urllib.parse.quote_plus(q), f"searching {q}")
    # system
    if re.search(r"^lock( (the )?(screen|computer))?$", t):
        return plan("argv", [["loginctl", "lock-session"], ["gnome-screensaver-command", "-l"]], "locking")
    if re.search(r"^(go to )?(sleep|suspend)$", t):
        return plan("argv", [["systemctl", "suspend"]], "going to sleep")
    if re.search(r"\b(focus|do not disturb|quiet mode)\b", t):
        return plan("dnd", msg="focus toggled")
    # open / launch / go to
    m = re.match(r"^(open|launch|start|run|show(?: me)?|go to|bring up|pull up)\s+(.+)$", t)
    if m:
        return _open_target(m.group(2), m.group(1))
    # bare noun ("downloads", "claude", "tech folder")
    p = _open_target(t)
    return p if p["kind"] != "none" else plan("none", msg=f"no command for “{t}”. say “help”")


CANCEL = re.compile(r"\b(cancel|never ?mind|nothing|forget it|stop|no)\b")
ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "last": -1,   # before numerals:
            "one": 0, "two": 1, "three": 2, "four": 3}                    # "the second one"


def answer(ctx, reply):
    """Turn the reply to Rayo's question (ctx from an 'ask' plan) into a plan."""
    r = clean(reply)
    if not r:
        return plan("none", msg="didn't catch that")
    if CANCEL.search(r):
        return plan("none", msg="okay, cancelled")
    exp = ctx.get("expect")
    if exp == "document":
        name = re.sub(r"^(?:(?:the|my|a)\s+)?(?:(?:document|file)\s+)?(?:(?:called|named)\s+)?", "", r)
        name = re.sub(r"\s+(document|file)$", "", name).strip()
        path = best(name, file_index(), 0.8)
        if path:
            return plan("open", path, f"opening {os.path.basename(path)}")
        if not ctx.get("retried"):
            return plan("ask", {"expect": "document", "retried": True},
                        f"couldn't find “{name}”. which document?")
        return plan("none", msg=f"no document like “{name}”")
    if exp == "folder":
        return _folders(re.sub(r"\s+folders?$", "", _strip_articles(r)))
    if exp == "app":
        return _open_target(r)
    if exp == "search":
        return plan("url", "https://www.google.com/search?q=" + urllib.parse.quote_plus(r), f"searching {r}")
    if exp == "browser":
        opts = ctx["options"]
        if re.search(r"\bdefault\b", r):
            return plan(*default_browser()[:2], msg="opening default browser")
        for word, i in ORDINALS.items():
            if re.search(rf"\b{word}\b", r) and -len(opts) <= i < len(opts):
                return plan("app", opts[i][1], f"opening {opts[i][0]}")
        for label, path in opts:
            if label in r or r in label:
                return plan("app", path, f"opening {label}")
        path = best(r, [(l, p, 0) for l, p in opts], 0.6)
        if path:
            return plan("app", path, "opening " + next(l for l, p in opts if p == path))
        return plan("none", msg=f"no browser called “{r}”")
    return plan("none", msg="never mind")


# ---- execute: plan → side effect ------------------------------------------------
def _popen(argv):
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _first_runnable(candidates):
    for argv in candidates:
        if shutil.which(argv[0]):
            _popen(argv)
            return True
    return False


def _open_path(path):
    if shutil.which("nautilus") and os.path.isdir(path):
        _popen(["nautilus", "--new-window", path])
    else:
        _popen(["xdg-open", path])


def _media(method):
    try:
        out = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                              "--object-path", "/org/freedesktop/DBus", "--method",
                              "org.freedesktop.DBus.ListNames"], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return False
    players = re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", out)
    for p in players:
        subprocess.run(["gdbus", "call", "--session", "--dest", p, "--object-path", "/org/mpris/MediaPlayer2",
                        "--method", f"org.mpris.MediaPlayer2.Player.{method}"],
                       capture_output=True, timeout=3)
    return bool(players)


def _volume(op):
    sink = "@DEFAULT_AUDIO_SINK@"
    cmd = {"+": ["wpctl", "set-volume", "-l", "1.0", sink, "10%+"],
           "-": ["wpctl", "set-volume", sink, "10%-"],
           "mute": ["wpctl", "set-mute", sink, "1"],
           "unmute": ["wpctl", "set-mute", sink, "0"]}[op]
    subprocess.run(cmd, capture_output=True, timeout=3)
    if op in ("+", "-"):
        out = subprocess.run(["wpctl", "get-volume", sink], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"([\d.]+)", out)
        if m:
            return f"volume {round(float(m.group(1)) * 100)}%"
    return None


def _toggle_dnd():
    cur = subprocess.run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
                         capture_output=True, text=True, timeout=3).stdout.strip()
    subprocess.run(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners",
                    "false" if cur == "true" else "true"], timeout=3)
    return "focus on" if cur == "true" else "focus off"


def execute(p):
    """Carry out a plan; return (message, hud_command_or_None)."""
    k, a, msg = p["kind"], p["arg"], p["msg"]
    try:
        if k == "app":
            _popen(["gio", "launch", a])
        elif k == "argv":
            if not _first_runnable(a):
                return "not available on this system", None
        elif k == "open":
            _open_path(a)
        elif k == "open_many":
            for path in a:
                _open_path(path)
        elif k == "url":
            _popen(["xdg-open", a])
        elif k == "volume":
            msg = _volume(a) or msg
        elif k == "media":
            if not _media(a):
                return "nothing is playing", None
        elif k == "dnd":
            msg = _toggle_dnd()
        elif k == "battery":
            import stats
            pct, charging, status, mins = stats.battery_info()
            eta = f", {mins // 60}h {mins % 60:02d}m {'to full' if charging else 'left'}" if mins else ""
            msg = f"battery {pct}%{' charging' if charging else ''}{eta}"
        elif k == "temp":
            import stats
            t = stats.cpu_temp()
            msg = f"cpu at {t}°c" if t is not None else "temperature unavailable"
        elif k == "hud":
            return msg, a
    except Exception as e:
        return f"failed: {e.__class__.__name__}", None
    return msg, None
