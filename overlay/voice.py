#!/usr/bin/env python3
"""
Rayo voice — ONE-SHOT, offline, push-to-talk command listener.

Design goal: zero idle cost. This is NOT a background daemon and NOT an
always-listening assistant. It is launched on demand (from the HUD hub's VOICE
item, or a keyboard shortcut you bind), records a single spoken command,
matches it to a whitelisted action, runs it, and exits. When you're not
talking to Rayo, nothing is running — so it can't slow the machine down.

Speech recognition is offline via Vosk (a small ~40MB model), so audio never
leaves your computer. Install everything with:  ./voice-setup.sh

Safety: destructive power actions (shutdown/restart) are deliberately NOT
voice-triggerable — a misheard word must never turn your PC off. Use the hub
or the on-screen buttons for those.
"""
import os, sys, json, shutil, subprocess

MODEL_DIR = os.environ.get("RAYO_VOSK_MODEL",
                           os.path.expanduser("~/.local/share/rayo-voice/model"))

# spoken phrase (any keyword) -> list of candidate argv (first that exists runs)
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
    print("[rayo-voice]", msg)
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "-a", "Rayo", "-t", "2500", "Rayo", msg], check=False)
        except Exception:
            pass


def run(candidates):
    for argv in candidates:
        if shutil.which(argv[0]):
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
    return False


def toggle_dnd():
    try:
        cur = subprocess.check_output(
            ["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
            text=True).strip()
        subprocess.run(["gsettings", "set", "org.gnome.desktop.notifications",
                        "show-banners", "false" if cur == "true" else "true"], check=False)
        return True
    except Exception:
        return False


def listen():
    """Record one utterance and return the recognised lower-case text."""
    try:
        import queue
        import sounddevice as sd
        import vosk
    except Exception:
        notify("voice not installed — run ./voice-setup.sh")
        sys.exit(1)
    if not os.path.isdir(MODEL_DIR):
        notify("voice model missing — run ./voice-setup.sh")
        sys.exit(1)

    vosk.SetLogLevel(-1)
    model = vosk.Model(MODEL_DIR)
    rec = vosk.KaldiRecognizer(model, 16000)
    q = queue.Queue()

    def cb(indata, frames, time_, status):
        q.put(bytes(indata))

    notify("listening…")
    import time as _t
    text = ""
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                           channels=1, callback=cb):
        start = _t.time()
        while _t.time() - start < 6:          # hard cap 6s
            data = q.get()
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
                if text:
                    break
    if not text:
        text = json.loads(rec.FinalResult()).get("text", "")
    return text.lower().strip()


def main():
    text = listen()
    if not text:
        notify("didn't catch that")
        return
    for words, candidates in COMMANDS:
        if any(w in text for w in words):
            ok = run(candidates)
            notify(f"“{text}” → {'opening ' + words[0] if ok else 'not available'}")
            return
    if any(w in text for w in DND_WORDS):
        toggle_dnd(); notify(f"“{text}” → focus toggled"); return
    if any(w in text for w in ("shut down", "shutdown", "restart", "reboot", "power off")):
        notify("power commands are on the hub, not voice (safety)"); return
    notify(f"“{text}” → no matching command")


if __name__ == "__main__":
    main()
