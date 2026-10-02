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
Power actions (shut down, restart, sleep, log out) always ask "Are you sure?" first; only a clear yes goes ahead.
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
    if re.fullmatch(r"(?:(?:the|my|your|rayo'?s?) )?(?:obsidian )?(?:vault|memory|notes)", t):
        return plan("vault", msg="opening memory")
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


POWER = {"poweroff": [["systemctl", "poweroff"]], "reboot": [["systemctl", "reboot"]],
         "suspend": [["systemctl", "suspend"]], "logout": [["gnome-session-quit", "--logout", "--no-prompt"]]}
_IT = r"(?: (?:the|my))?(?: (?:computer|laptop|pc|machine|system|rayo|it))?(?: (?:now|please|right now))?"
POWER_PHRASES = [
    ("poweroff", rf"(?:shut ?down|power off|power down|turn off|switch off){_IT}|shut it down|shutdown"),
    ("reboot", rf"(?:restart|reboot){_IT}"),
    ("suspend", rf"(?:go to sleep|sleep|suspend|hibernate|sleep mode|put{_IT} (?:to|in|into) sleep)(?: (?:now|please))?"),
    ("logout", r"(?:log ?out|sign ?out|log me out|sign me out)(?: (?:now|please))?"),
]


def power_action(t):
    """'shut down the computer' → 'poweroff'. Whole-sentence match only, so 'how do I restart my router' is just a question."""
    for action, pat in POWER_PHRASES:
        if re.fullmatch(pat, t):
            return action
    return None


QUESTION = re.compile(r"^(what|what's|whats|who|who's|why|how|when|where|which|is|are|can|could|should|"
                      r"do|does|did|will|would|was|were)\b")
NOISE = {"the", "a", "huh", "uh", "um", "hmm", "and", "okay", "yes", "yeah", "oh"}


ACTIONISH = re.compile(r"\b(open|launch|pull up|bring up|start|play|pause|search|look up|find|check|weather|rain|forecast|"
                       r"battery|volume|louder|quieter|mute|status|remember|show|next|previous|skip|resume)\b")


def compound(t):
    """'open downloads and check the weather': two actions in one breath. The brain picks the tools."""
    parts = re.split(r"\b(?:and then|and also|and|then|also)\b|[,;]", t)
    return len(parts) >= 2 and sum(1 for p in parts if ACTIONISH.search(p)) >= 2


MULTI_OK = {"app", "open", "open_many", "url", "volume", "media", "weather", "battery", "temp", "status",
            "say", "remember", "recall", "hud", "vault", "speech", "alerts"}


def _steps(t):
    """Split 'open x and check y' into plans; None unless every piece is a plain, safe command."""
    plans = []
    for part in re.split(r"\b(?:and then|and also|and|then|also)\b|[,;]", t):
        part = re.sub(r"^(?:please |could you |can you )?(?:tell me|let me know|give me)(?: about)?(?: the)? ", "", part.strip())
        if not part:
            continue
        p = resolve(part)
        if p["kind"] not in MULTI_OK:
            return None
        plans.append(p)
    return plans if len(plans) >= 2 and len(plans) <= 3 else None


def _brain(q):
    """No command matched: ask the local LLM (overlay/brain.py). Talk only, never act."""
    if q in NOISE or len(q) < 4:
        return plan("none", msg="didn't catch that")
    return plan("brain", q, "thinking…")


def resolve(text):
    import soul
    small = soul.match(text)                      # small talk first: "thank you" would be stripped by clean(), "who are you" would reach the brain
    if small:
        return plan("soul", None, small)
    t = clean(text)
    if not t:
        return plan("none", msg="didn't catch that")
    fu = soul.followup(t)                         # "and tomorrow?" after a forecast, "say that again"
    if fu:
        return plan("soul", None, fu[1]) if fu[0] == "repeat" else plan("weather", fu[1], "checking the weather")
    act = power_action(t)
    if act and not __import__("config").get("security", "voice_power", True):
        return plan("say", msg="voice power commands are switched off. Use the hub instead")
    if act:                                   # never acts on the first ask: she always checks first
        import persona
        return plan("ask", {"expect": "confirm", "action": act}, persona.confirm_question(act))
    if re.fullmatch(r"(what can you do|what do|what do you do|help|commands|what are your commands)", t) or t.startswith("help "):
        return plan("say", msg="try: open claude · open downloads · search for jollof rice · or just ask me anything")
    # memory (the Obsidian vault, overlay/memory.py)
    m = re.match(r"^(?:remember|don'?t forget|make a note|take a note|note)(?: that| this| of)?[:,]?\s+(.+)$", t)
    if m:
        return plan("remember", m.group(1), "")
    if re.fullmatch(r"forget (that|it|the last (thing|one)|what i (just )?said)", t):
        return plan("forget")
    if re.fullmatch(r"(what do you (remember|know about me)|what have i told you|what('?s| is) in your memory)", t):
        return plan("recall")
    if compound(t):
        steps = _steps(t)                        # every piece understood -> just do them, no LLM needed
        return plan("multi", steps, "") if steps else _brain(t)
    # things Rayo will not do: say so plainly (the model would otherwise claim it had)
    if re.match(r"^(delete|erase|wipe|remove|trash|format|uninstall|empty)\b", t) and not t.startswith(("remove that", "remove the last")):
        return plan("say", msg="I don't delete things. That one's for your own hands")
    if re.match(r"^(send|text|whatsapp|email|message|dm|reply to|call|phone)\b", t):
        return plan("say", msg="I can't send messages or make calls yet. that's coming soon")
    # the cloud brain (overlay/cloud.py): Groq every day, Claude on request
    m = re.match(r"^((?:(?:hey|ok|okay) )?(?:(?:ask|tell) )?)(claude|groq|the cloud|the big brain|the smart brain)[,:]?\s+(.+)$", t)
    if m and (m.group(1).strip() or re.match(
            r"(?:tell|explain|what|why|how|who|when|where|can|could|write|summari[sz]e|give|help|suggest|compare|translate|define|describe|is|are|should)\b", m.group(3))):
        return plan("cloud", m.group(3), "claude" if m.group(2) == "claude" else "")
    if re.fullmatch(r"(?:claude usage|cloud usage|groq usage|how much (?:have you spent|has (?:claude|groq|the cloud) cost me|is (?:claude|the cloud) costing me|did (?:claude|the cloud) cost)|how much (?:am i|have i been) spending on (?:claude|the cloud))", t):
        return plan("cloudusage")
    if re.fullmatch(r"(?:always use the cloud|only use the cloud)", t):
        return plan("cloudmode", "always", "okay, I'll ask the cloud whenever I can")
    if re.fullmatch(r"(?:use the cloud|turn on the cloud|enable the cloud|cloud on|go online)", t):
        return plan("cloudmode", "auto", "okay, I'll use the cloud for the harder questions")
    if re.fullmatch(r"(?:stop using the cloud|turn off the cloud|disable the cloud|cloud off|stay offline|go offline|offline mode|local only|use the local brain|use your own brain)", t):
        return plan("cloudmode", "off", "okay, staying offline. just my small brain from now on")
    m = re.fullmatch(r"use (claude|groq)(?: as my (?:main|everyday|default) brain)?", t)
    if m:
        who = "anthropic" if m.group(1) == "claude" else "groq"
        return plan("cloudprovider", who, "okay, Claude is my everyday cloud brain now. that costs a little" if who == "anthropic"
                    else "okay, Groq is my everyday cloud brain")
    # awareness (overlay/awareness.py)
    if re.search(r"\b(status|system) report\b|^(how('?s| is) (the )?(system|laptop|computer|pc)( doing)?|system status|status)$", t):
        return plan("status")
    if re.search(r"\b(stop|disable|no more|turn off|silence)\b.*\b(alerts?|warnings?|notifications?)\b", t):
        return plan("alerts", False, "okay, no more alerts")
    if re.search(r"\b(alerts?|warnings?)\b.*\b(on|back|enable)\b|\b(start|enable|turn on)\b.*\b(alerts?|warnings?)\b", t):
        return plan("alerts", True, "alerts on. I'll speak up if something needs you")
    # weather (before the brain: questions about rain are live data, not trivia)
    if re.search(r"\b(weather|forecast|rain(ing|y)?|umbrella|sunny|cold outside|hot outside|temperature outside|outside temperature|outside)\b", t) \
            and not re.match(r"^(tell me about|explain|define|describe|write|summari[sz]e|what (is|are) (a |an )?(rain|weather) ?(forest|cycle|pattern)s?)\b", t):
        when = next((w for w in ("tonight", "tomorrow", "today", "this evening", "this morning", "later")
                     if w in t), "now")
        return plan("weather", when, "checking the weather")
    # things Rayo can't reach yet: say so plainly instead of letting the brain guess
    if re.match(r"^(check|read|any|do i have|send|reply|show|whats on|what's on|what is on)\b.*\b(e ?mails?|mail|inbox|messages?|whatsapp|calendar|meetings?|schedule)\b", t):
        return plan("say", msg="I can't reach your email, messages or calendar yet. that's coming soon")
    # the brain: "ask …", "tell me …", "explain …", or a long question
    m = re.match(r"^(?:ask|question|ask (?:you|the brain)|i have a question)\s*(.*)$", t)
    if m and m.group(1):
        return _brain(m.group(1))
    if re.match(r"^(tell me|explain|define|describe|who|why|summari[sz]e|give me|write|suggest|translate)\b", t) \
            or (QUESTION.match(t) and len(t.split()) > 5):
        return _brain(t)
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
    # soul: follow-up context and small talk are handled at the top of resolve()
    if re.fullmatch(r"(?:not now|snooze (?:the )?alerts?(?: for (?:an|one) hour)?|ignore (?:that|the alert)|quiet for an hour)", t):
        return plan("snooze", msg="okay, quiet for an hour. I'll keep watching, silently")
    # personality
    if re.search(r"\b(be nice|no sarcasm|stop being sarcastic|stop the sarcasm|turn off (the )?sarcasm|sarcasm off|be serious|be polite)\b", t):
        return plan("persona", "off", "fine. sarcasm off. I'll be unbearably polite instead")
    if re.search(r"\b(less sarcastic|tone it down|mild sarcasm|a bit less sarcastic|sarcasm (down|mild))\b", t):
        return plan("persona", "mild", "mild sarcasm, then. a shame")
    if re.search(r"\b(be sarcastic|sarcasm on|more sarcasm|full sarcasm|turn on (the )?sarcasm|sarcasm back)\b", t):
        return plan("persona", "full", "sarcasm restored. you're welcome")
    # Rayo's own voice
    if re.search(r"\b(stop talking|be quiet|shut up|silent mode|mute yourself|don'?t (talk|speak)|stop speaking)\b", t):
        return plan("speech", False, "okay, captions only")
    if re.fullmatch(r"(talk to me|speak (again|to me|up)|voice on|you can (talk|speak)( again)?|start talking|unmute yourself)", t):
        return plan("speech", True, "voice on. I'm back")
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
    if re.search(r"^(play|pause|resume|stop)( (some |the |my )?(music|songs?|videos?|it|something))?$", t):
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
    if re.search(r"\b(focus|do not disturb|quiet mode)\b", t):
        return plan("dnd", msg="focus toggled")
    # open / launch / go to
    m = re.match(r"^(open|launch|start|run|show(?: me)?|go to|bring up|pull up)\s+(.+)$", t)
    if m:
        return _open_target(m.group(2), m.group(1))
    # bare noun ("downloads", "claude", "tech folder"); anything else goes to the brain
    if len(t.split()) <= 3:
        p = _open_target(t)
        if p["kind"] != "none":
            return p
    return _brain(t)


CANCEL = re.compile(r"\b(cancel|never ?mind|nothing|forget it|stop|no)\b")
ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "last": -1,   # before numerals:
            "one": 0, "two": 1, "three": 2, "four": 3}                    # "the second one"


YES = re.compile(r"\b(yes|yeah|yep|yup|sure|confirm|confirmed|do it|go ahead|affirmative|absolutely|i'?m sure|please do)\b")
NO = re.compile(r"\b(no|nope|nah|don'?t|do not|cancel|stop|wait|never ?mind|negative|abort|not)\b")


def answer(ctx, reply):
    """Turn the reply to Rayo's question (ctx from an 'ask' plan) into a plan."""
    if ctx.get("expect") == "confirm":        # anything but a clear yes is a no
        r = clean(reply)
        if r and YES.search(r) and not NO.search(r):
            return plan("power", ctx["action"], "")
        return plan("none", msg="okay, cancelled" if r else "didn't hear a yes, so I'm staying on")
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


def _weather(when):
    """Spoken forecast from wttr.in (the HUD's weather source)."""
    import json, urllib.request
    try:
        with urllib.request.urlopen("https://wttr.in/?format=j1", timeout=10) as r:
            d = json.load(r)
    except Exception:
        return "I can't reach the weather service right now"
    now = d["current_condition"][0]
    desc = lambda h: h["weatherDesc"][0]["value"].strip().lower()
    if when == "now":
        return f"it's {now['temp_C']}°C and {desc(now)}, feels like {now['FeelsLikeC']}°C"
    today, tomorrow = d["weather"][0]["hourly"], d["weather"][1]["hourly"]
    hour = int(time.strftime("%H")) * 100
    if when == "tomorrow":
        hours, label = tomorrow, "tomorrow"
    elif when in ("tonight", "this evening"):
        hours, label = [h for h in today if int(h["time"]) >= 1800] + tomorrow[:1], "tonight"
    elif when == "this morning":
        hours, label = [h for h in today if 600 <= int(h["time"]) <= 1200], "this morning"
    else:                                      # today / later: what's left of today
        hours, label = [h for h in today if int(h["time"]) + 300 > hour] or today[-2:], "later today"
    rain = max(int(h["chanceofrain"]) for h in hours)
    temps = [int(h["tempC"]) for h in hours]
    wettest = max(hours, key=lambda h: int(h["chanceofrain"]))
    verdict = ("yes, rain is likely" if rain >= 60 else "maybe, there's some chance of rain" if rain >= 30
               else "rain is unlikely")
    span = f"{min(temps)}°C" if min(temps) == max(temps) else f"{min(temps)} to {max(temps)}°C"
    return f"{label}: {verdict}, {rain}% chance, {desc(wettest)}, {span}"


def execute(p):
    """Carry out a plan; return (message, hud_command_or_None)."""
    k, a, msg = p["kind"], p["arg"], p["msg"]
    if k == "brain":
        import brain
        return brain.ask(a), None
    if k == "multi":                                 # several commands in one sentence
        msgs, huds = [], []
        for step in a:
            m, h = execute(step)
            msgs.append(m)
            if h:
                huds.append(h)
        return "; ".join(msgs), (huds[0] if huds else None)
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
        elif k == "weather":
            msg = _weather(a)
        elif k == "battery":
            import stats
            pct, charging, status, mins = stats.battery_info()
            eta = f", {mins // 60}h {mins % 60:02d}m {'to full' if charging else 'left'}" if mins else ""
            msg = f"battery {pct}%{' charging' if charging else ''}{eta}"
        elif k == "temp":
            import stats
            t = stats.cpu_temp()
            msg = f"cpu at {t}°c" if t is not None else "temperature unavailable"
        elif k in ("remember", "forget", "recall"):
            import memory
            msg = {"remember": lambda: memory.remember(a), "forget": memory.forget_last,
                   "recall": memory.recall}[k]()
        elif k == "vault":
            import memory
            memory.ensure()
            handler = subprocess.run(["xdg-mime", "query", "default", "x-scheme-handler/obsidian"],
                                     capture_output=True, text=True).stdout.strip()
            _popen(["xdg-open", memory.open_uri()]) if handler else _open_path(memory.vault())
        elif k == "power":
            if not _first_runnable(POWER[a]):
                return "I couldn't do that on this system", None
        elif k == "cloudmode":
            import config
            config.set("cloud", "mode", a)
        elif k == "cloudprovider":
            import config
            config.set("cloud", "provider", a)
        elif k == "cloudusage":
            import cloud
            msg = cloud.usage_text()
        elif k == "snooze":
            import config
            config.set("awareness", "snooze_until", time.time() + 3600)
        elif k == "soul":
            pass                                     # the reply is already in msg
        elif k == "persona":
            import persona
            persona.set_level(a)
        elif k == "status":
            import awareness
            msg = awareness.report()
        elif k == "alerts":
            import config
            config.set("awareness", "on", bool(a))
        elif k == "speech":
            import config
            config.set("speech", "on", bool(a))
        elif k == "hud":
            return msg, a
    except Exception as e:
        return f"failed: {e.__class__.__name__}", None
    return msg, None
