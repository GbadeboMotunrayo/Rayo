#!/usr/bin/env python3
"""
Rayo voice — offline speech commands. Two modes:

  voice.py            ONE-SHOT push-to-talk: record one command, run it, exit.
                      Zero idle cost (nothing runs when you're not talking).
  voice.py --wake     WAKE-WORD daemon: keep an ear open for "Rayo" / "wake up",
                      then take one command. Small continuous CPU while on; the
                      HUD toggles it (hub -> VOICE), off by default.

Recognition runs on-device via Vosk (small ~40MB model) — audio never leaves the
machine. Install with ./voice-setup.sh . Destructive power actions
(shutdown/restart) are intentionally NOT voice-triggerable.

HUD protocol: lines on stdout starting with "@" are state events the overlay
forwards to the HUD (the reactor visualises them):
  @armed · @listening · @level <0..1> · @heard <text> · @result <msg> ·
  @idle · @error <msg> · @off
"""
import os, sys, json, math, shutil, subprocess, signal
from array import array

MODEL_DIR = os.environ.get("RAYO_VOSK_MODEL",
                           os.path.expanduser("~/.local/share/rayo-voice/model"))
RATE, BLOCK = 16000, 4000                     # 0.25s blocks → 4 level updates/s
# "rayo" is not an English word, so the English model may not know it. We also
# listen for how it sounds ("ray oh"), and drop any phrase whose words are
# missing from the model's vocabulary (when the model exposes it).
WAKE_GRAMMAR = ["rayo", "ray oh", "hey ray oh", "wake up"]
WAKE_MATCH = ("rayo", "ray oh", "wake up")
WAKE_MIN_CONF = 0.65                          # confidence gate vs false wakes

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
STOP = {"v": False}


# ---- output ----------------------------------------------------------------
def emit(kind, payload=""):
    print(f"@{kind} {payload}".rstrip(), flush=True)


def notify(msg):
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "-a", "Rayo", "-t", "2500", "Rayo", msg], check=False)
        except Exception:
            pass


def chime():
    for c in (["canberra-gtk-play", "-i", "message"],
              ["pw-play", "/usr/share/sounds/freedesktop/stereo/message.oga"],
              ["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"]):
        if shutil.which(c[0]):
            try:
                subprocess.Popen(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            return


def fail(msg):
    emit("error", msg); notify(msg); emit("off"); sys.exit(1)


# ---- actions ---------------------------------------------------------------
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
    """Run the command matching `text`; return a short human result."""
    if not text:
        return "didn't catch that"
    for words, candidates in COMMANDS:
        if any(w in text for w in words):
            return f"opening {words[0]}" if run(candidates) else f"{words[0]} not available"
    if any(w in text for w in DND_WORDS):
        return "focus toggled" if toggle_dnd() else "focus unavailable"
    if any(w in text for w in ("shut down", "shutdown", "restart", "reboot", "power off")):
        return "power stays on the hub (safety)"
    return "no matching command"


def report(text):
    emit("heard", text)
    result = act_on(text)
    emit("result", result)
    notify(f"“{text}” → {result}" if text else result)


# ---- audio -----------------------------------------------------------------
def load():
    try:
        import queue  # noqa: F401
        import sounddevice  # noqa: F401
        import vosk
    except Exception:
        fail("voice not installed — run ./voice-setup.sh")
    if not os.path.isdir(MODEL_DIR):
        fail("voice model missing — run ./voice-setup.sh")
    vosk.SetLogLevel(-1)
    return vosk.Model(MODEL_DIR)


def open_stream(q):
    import sounddevice as sd
    try:
        return sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, dtype="int16",
                                 channels=1, callback=lambda i, f, t, s: q.put(bytes(i)))
    except Exception as e:
        fail(f"microphone unavailable ({e.__class__.__name__})")


def level(data):
    """0..1 loudness of one int16 block (log scale, speech ~0.4-0.9)."""
    a = array("h", data)
    if not a:
        return 0.0
    rms = math.sqrt(sum(s * s for s in a) / len(a))
    return max(0.0, min(1.0, (20 * math.log10(rms + 1) - 38) / 40))


def capture(model, q, seconds=6):
    """Recognise one full utterance from the shared audio queue."""
    import queue, time, vosk
    rec = vosk.KaldiRecognizer(model, RATE)
    text, start = "", time.time()
    while time.time() - start < seconds and not STOP["v"]:
        try:
            data = q.get(timeout=0.5)
        except queue.Empty:
            continue
        emit("level", f"{level(data):.2f}")
        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "")
            if text:
                break
    if not text:
        text = json.loads(rec.FinalResult()).get("text", "")
    emit("level", "0")
    return text.lower().strip()


def wake_grammar(model_dir):
    """Keep only wake phrases whose words the model actually knows."""
    vocab_file = os.path.join(model_dir, "graph", "words.txt")
    phrases = list(WAKE_GRAMMAR)
    if os.path.isfile(vocab_file):
        vocab = {ln.split()[0] for ln in open(vocab_file, errors="ignore") if ln.strip()}
        phrases = [p for p in phrases if all(w in vocab for w in p.split())] or ["wake up"]
    return phrases


def is_wake(result_json):
    r = json.loads(result_json)
    text = r.get("text", "")
    if not any(w in text for w in WAKE_MATCH):
        return False
    confs = [w.get("conf", 1.0) for w in r.get("result", [])]
    return (min(confs) if confs else 1.0) >= WAKE_MIN_CONF


# ---- modes -----------------------------------------------------------------
def one_shot():
    import queue
    model, q = load(), queue.Queue()
    emit("listening"); notify("listening…")
    with open_stream(q):
        text = capture(model, q)
    report(text)
    emit("off")


def wake_loop():
    import queue
    model, q = load(), queue.Queue()          # load() reports missing deps to the HUD
    import vosk
    grammar = wake_grammar(MODEL_DIR)
    signal.signal(signal.SIGTERM, lambda *_: STOP.__setitem__("v", True))
    signal.signal(signal.SIGINT, lambda *_: STOP.__setitem__("v", True))

    def wake_rec():
        rec = vosk.KaldiRecognizer(model, RATE, json.dumps(grammar + ["[unk]"]))
        rec.SetWords(True)
        return rec

    with open_stream(q):                      # ONE mic stream for everything
        emit("armed"); notify("Rayo is listening — say “Rayo”")
        rec = wake_rec()
        while not STOP["v"]:
            try:
                data = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if rec.AcceptWaveform(data) and is_wake(rec.Result()):
                chime(); emit("listening")
                while not q.empty():          # discard the wake phrase itself
                    try: q.get_nowait()
                    except queue.Empty: break
                report(capture(model, q))
                emit("idle")
                rec = wake_rec()
    emit("off")


if __name__ == "__main__":
    wake_loop() if "--wake" in sys.argv[1:] else one_shot()
