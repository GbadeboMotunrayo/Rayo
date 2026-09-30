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
import os, sys, json, math, shutil, subprocess, signal, threading
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


# ---- actions (see commands.py for everything Rayo understands) ------------
import commands


MAX_FOLLOWUPS = 2                               # "which document?" → retry once → give up


def drain(q):
    import queue
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


def report(text, model=None, q=None):
    """Run a command. If Rayo needs a detail ("which document?") it asks and
    hears the answer on the same open mic, no wake word needed."""
    emit("heard", text)
    p = commands.resolve(text)
    for _ in range(MAX_FOLLOWUPS):
        if p["kind"] != "ask" or model is None or STOP["v"]:
            break
        emit("ask", p["msg"]); chime()
        drain(q)                                # don't hear the chime / our own question
        reply = capture(model, q)
        emit("heard", reply)
        p = commands.answer(p["arg"], reply)
    if p["kind"] == "ask":
        p = commands.plan("none", msg="okay, never mind")
    msg, hud = commands.execute(p)
    if hud:
        emit("do", hud)                        # HUD-side actions: theme, bench
    emit("result", msg)
    notify(f"“{text}” → {msg}" if text else msg)


# ---- audio -----------------------------------------------------------------
def load():
    try:
        import vosk
    except Exception:
        fail("voice not installed — run ./voice-setup.sh")
    if not os.path.isdir(MODEL_DIR):
        fail("voice model missing — run ./voice-setup.sh")
    vosk.SetLogLevel(-1)
    return vosk.Model(MODEL_DIR)


# The system's own recorders (PipeWire first, ALSA second) — no PortAudio needed.
RECORDERS = [
    ["pw-record", "--raw", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
    ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
]


class Mic:
    """The microphone as int16 blocks on a queue."""
    def __init__(self, q):
        self.q, self.proc, self.sd = q, None, None

    def __enter__(self):
        for cmd in RECORDERS:
            if shutil.which(cmd[0]):
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                threading.Thread(target=self._pump, daemon=True).start()
                return self
        try:                                   # last resort: PortAudio via sounddevice
            import sounddevice as sd
            self.sd = sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, dtype="int16", channels=1,
                                        callback=lambda i, f, t, s: self.q.put(bytes(i)))
            self.sd.__enter__()
            return self
        except Exception:
            fail("no microphone recorder found (need pw-record or arecord)")

    def _pump(self):
        while True:
            b = self.proc.stdout.read(BLOCK * 2)
            if not b:
                break
            self.q.put(b)

    def alive(self):
        return self.sd is not None or (self.proc is not None and self.proc.poll() is None)

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except Exception:
                self.proc.kill()
        if self.sd:
            self.sd.__exit__(*exc)


def open_stream(q):
    return Mic(q)


def level(data):
    """0..1 loudness of one int16 block (log scale, speech ~0.4-0.9)."""
    a = array("h", data)
    if not a:
        return 0.0
    rms = math.sqrt(sum(s * s for s in a) / len(a))
    return max(0.0, min(1.0, (20 * math.log10(rms + 1) - 32) / 36))   # tuned for laptop mics


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
        report(capture(model, q), model, q)    # mic stays open for follow-ups
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

    with open_stream(q) as mic:               # ONE mic stream for everything
        emit("armed"); notify("Rayo is listening — say “Rayo”")
        rec = wake_rec()
        while not STOP["v"]:
            try:
                data = q.get(timeout=0.5)
            except queue.Empty:
                if not mic.alive():
                    fail("microphone stopped — is a mic connected and unmuted?")
                continue
            if rec.AcceptWaveform(data) and is_wake(rec.Result()):
                chime(); emit("listening")
                while not q.empty():          # discard the wake phrase itself
                    try: q.get_nowait()
                    except queue.Empty: break
                report(capture(model, q), model, q)
                emit("idle")
                rec = wake_rec()
    emit("off")


if __name__ == "__main__":
    wake_loop() if "--wake" in sys.argv[1:] else one_shot()
