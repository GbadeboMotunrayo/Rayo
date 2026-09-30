#!/usr/bin/env python3
"""
Rayo voice — offline speech commands. Two modes:

  voice.py            ONE-SHOT push-to-talk: record one command, run it, exit.
                      Zero idle cost (nothing runs when you're not talking).
  voice.py --wake     WAKE-WORD daemon: keep an ear open for "Rayo" / "wake up",
                      then take one command. Small continuous CPU while on;
                      the HUD toggles this on/off (VOICE in the hub), off by
                      default, so it only listens when you ask it to.

Recognition is on-device via Vosk (small ~40MB model) — audio never leaves the
machine. Install with ./voice-setup.sh . Destructive power actions
(shutdown/restart) are intentionally NOT voice-triggerable.
"""
import os, sys, json, shutil, subprocess, signal

MODEL_DIR = os.environ.get("RAYO_VOSK_MODEL",
                           os.path.expanduser("~/.local/share/rayo-voice/model"))
WAKE_WORDS = ("rayo", "wake up", "hey rayo")

COMMANDS = [
    (("browser", "internet", "firefox", "web", "chrome"), [["firefox"], ["xdg-open", "https://duckduckgo.com"]]),
    (("files", "file manager", "folder", "explorer"),     [["nautilus", "--new-window"], ["xdg-open", os.path.expanduser("~")]]),
    (("terminal", "console", "shell"),                    [["ptyxis"], ["kgx"], ["gnome-terminal"], ["xterm"]]),
    (("settings", "preferences"),                         [["gnome-control-center"]]),
    (("display", "displays", "monitor", "screen"),        [["gnome-control-center", "display"]]),
    (("lock", "lock screen"),                             [["loginctl", "lock-session"], ["gnome-screensaver-command", "-l"]]),
    (("sleep", "suspend"),                                [["systemctl", "suspend"]]),
]
DND_WORDS = ("focus", "do not disturb", "quiet", "silence")


def notify(msg):
    print("[rayo-voice]", msg, flush=True)
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "-a", "Rayo", "-t", "2500", "Rayo", msg], check=False)
        except Exception:
            pass


def chime():
    for c in (["canberra-gtk-play", "-i", "message"], ["pw-play", "/usr/share/sounds/freedesktop/stereo/message.oga"],
              ["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"]):
        if shutil.which(c[0]):
            try:
                subprocess.Popen(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            return


def run(candidates):
    for argv in candidates:
        if shutil.which(argv[0]):
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
    return False


def toggle_dnd():
    try:
        cur = subprocess.check_output(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"], text=True).strip()
        subprocess.run(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners",
                        "false" if cur == "true" else "true"], check=False)
        return True
    except Exception:
        return False


def act_on(text):
    """Match recognised text to a command and run it."""
    if not text:
        notify("didn't catch that"); return
    for words, candidates in COMMANDS:
        if any(w in text for w in words):
            ok = run(candidates)
            notify(f"“{text}” → {'opening ' + words[0] if ok else 'not available'}"); return
    if any(w in text for w in DND_WORDS):
        toggle_dnd(); notify(f"“{text}” → focus toggled"); return
    if any(w in text for w in ("shut down", "shutdown", "restart", "reboot", "power off")):
        notify("power stays on the hub, not voice (safety)"); return
    notify(f"“{text}” → no matching command")


def _deps():
    try:
        import queue, sounddevice, vosk  # noqa
        return True
    except Exception:
        notify("voice not installed — run ./voice-setup.sh"); return False


def _load_model():
    import vosk
    vosk.SetLogLevel(-1)
    if not os.path.isdir(MODEL_DIR):
        notify("voice model missing — run ./voice-setup.sh"); sys.exit(1)
    return vosk.Model(MODEL_DIR)


def _stream(cb):
    import sounddevice as sd
    return sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16", channels=1, callback=cb)


def capture(model, seconds=6):
    """Record and return one full command utterance (lower-case)."""
    import queue, vosk
    q = queue.Queue()
    rec = vosk.KaldiRecognizer(model, 16000)
    import time as _t
    text = ""
    with _stream(lambda i, f, t, s: q.put(bytes(i))):
        start = _t.time()
        while _t.time() - start < seconds:
            data = q.get()
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
                if text:
                    break
    if not text:
        text = json.loads(rec.FinalResult()).get("text", "")
    return text.lower().strip()


def one_shot():
    if not _deps():
        sys.exit(1)
    notify("listening…")
    act_on(capture(_load_model()))


def wake_loop():
    if not _deps():
        sys.exit(1)
    import queue, vosk
    model = _load_model()
    grammar = json.dumps(list(WAKE_WORDS) + ["[unk]"])
    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("v", True))
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("v", True))
    notify("Rayo is listening — say “Rayo”")
    q = queue.Queue()
    with _stream(lambda i, f, t, s: q.put(bytes(i))):
        rec = vosk.KaldiRecognizer(model, 16000, grammar)
        while not stop["v"]:
            try:
                data = q.get(timeout=0.5)
            except Exception:
                continue
            if rec.AcceptWaveform(data):
                txt = json.loads(rec.Result()).get("text", "")
                if any(w in txt for w in ("rayo", "wake up")):
                    chime(); notify("yes?")
                    while not q.empty():
                        try: q.get_nowait()
                        except Exception: break
                    act_on(capture(model))
                    rec = vosk.KaldiRecognizer(model, 16000, grammar)
    notify("Rayo voice off")


if __name__ == "__main__":
    if "--wake" in sys.argv[1:]:
        wake_loop()
    else:
        one_shot()
