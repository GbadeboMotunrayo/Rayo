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
import os, re, sys, json, time, math, shutil, subprocess, signal, threading
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
_emit_lock = threading.Lock()


def emit(kind, payload=""):
    line = f"@{kind} {' '.join(str(payload).split())}".rstrip() + "\n"   # one line, whole (threads share stdout)
    with _emit_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


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


def brain_warm():
    try:
        import brain
        brain.warm()
    except Exception:
        pass


_speaker = []


def speaker():
    """Rayo's voice (overlay/speech.py). Without Piper it stays silent and the HUD captions carry on."""
    if not _speaker:
        import speech
        _speaker.append(speech.Speaker(emit))
    return _speaker[0]


def speak(text):
    spk = speaker()
    spk.say(text)
    spk.wait()


def remember_exchange(heard, reply):
    """Today's note in the Obsidian vault (overlay/memory.py); never breaks the voice loop."""
    try:
        import memory
        memory.log(heard, reply)
    except Exception:
        pass


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
        emit("ask", p["msg"])
        if speaker().available():
            speak(p["msg"]); emit("ask", p["msg"])  # back to listening once the question is said
        else:
            chime()
        drain(q)                                # don't hear the chime / our own question
        reply = capture(model, q)
        emit("heard", reply)
        p = commands.answer(p["arg"], reply)
    if p["kind"] == "ask":
        p = commands.plan("none", msg="okay, never mind")
    if p["kind"] == "brain":                    # no command matched: think (and maybe act)
        import brain, speech, tools
        emit("thinking", "")
        import commands as _c
        if brain.wants_action(p["arg"]) and not brain.tools_enabled() and not _c.QUESTION.match(p["arg"]) \
                and not re.match(r"^(tell me|explain|define|describe|why|who|write|summari[sz]e)\b", p["arg"]):
            import persona                      # an action she has no command for: say so, don't make something up
            msg = persona.flavor("none", "I don't know how to do that one yet. Try: open something, search for something, or ask me a question")
            emit("result", msg)
            remember_exchange(text, msg)
            notify(msg)
            speak(msg)
            return
        if brain.wants_action(p["arg"]) and brain.tools_enabled():   # opt-in: the brain may pick tools
            r = brain.act(p["arg"])
            if r["calls"]:
                msg, huds = tools.run(r["calls"])
                for h in huds:
                    emit("do", h)
                msg = msg or r["text"]
                emit("result", msg)
                remember_exchange(text, msg)
                notify(f"“{text}” → {msg}")
                speak(msg)
                return
            import persona
            msg = persona.brain_quip(r["text"])     # it just talked: show it, then say it
            emit("answer", msg)
            remember_exchange(text, msg)
            notify(msg)
            speak(msg)
            return
        spoken = speech.Sentences(speaker())      # a question: speak each sentence as soon as it's complete

        def partial(t):
            emit("say", t)
            spoken.feed(t)
        import persona
        msg = persona.brain_quip(brain.ask(p["arg"], partial))   # the answer streams; the jab lands at the end
        emit("answer", msg)
        remember_exchange(text, msg)
        spoken.finish(msg)
        speaker().wait()
        notify(msg)
        return
    if p["kind"] == "power":                   # confirmed: say goodbye first, then do it
        import persona
        bye = persona.farewell(p["arg"])
        emit("result", bye)
        remember_exchange(text, bye)
        notify(bye)
        speak(bye)
        time.sleep(0.6)
        commands.execute(p)
        return
    msg, hud = commands.execute(p)
    if p["kind"] not in ("multi", "power"):
        import persona
        msg = persona.flavor(p["kind"], msg)   # sarcasm goes around the answer, never instead of it
    if hud:
        emit("do", hud)                        # HUD-side actions: theme, bench
    emit("result", msg)
    remember_exchange(text, msg)
    notify(f"“{text}” → {msg}" if text else msg)
    speak(msg)


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


WHISPER_DIR = os.path.expanduser("~/.local/share/rayo-voice/whisper")
HINTS = ("Rayo. Open, launch, remember, search. Paystack, Obsidian, Firefox, Brave, Chromium, "
         "Claude, WhatsApp, YouTube, Gmail, folder, document.")
_whisper = []


def whisper():
    """Whisper for what you say after the wake word (far better with names than Vosk-small).
    ~200MB once loaded; {"ears": {"engine": "vosk"}} in the config turns it off."""
    import config
    if config.get("ears", "engine", "whisper") != "whisper":
        return None
    if not _whisper:
        try:
            from faster_whisper import WhisperModel
            _whisper.append(WhisperModel(config.get("ears", "model", "base.en"), device="cpu",
                                         compute_type="int8", cpu_threads=4, download_root=WHISPER_DIR))
        except Exception:
            _whisper.append(None)              # not installed: Vosk transcribes instead
    return _whisper[0]


def whisper_warm():
    threading.Thread(target=whisper, daemon=True).start()


def transcribe(audio):
    """16kHz s16 bytes → lower-case words, or None if Whisper isn't available."""
    wm = whisper()
    if wm is None or len(audio) < RATE // 2:   # under a quarter second: nothing said
        return None
    import numpy as np, config
    pcm = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768
    segs, _ = wm.transcribe(pcm, language="en", beam_size=1, vad_filter=True, condition_on_previous_text=False,
                            initial_prompt=HINTS + " " + " ".join(config.get("ears", "vocab", [])))
    text = " ".join(s.text for s in segs)
    return " ".join(re.sub(r"[^\w\s']", " ", text).lower().split())


def capture(model, q, seconds=6):
    """Hear one full utterance from the shared audio queue. Vosk spots where you
    stop talking; Whisper (if installed) then transcribes the whole clip."""
    import queue, time, vosk
    rec = vosk.KaldiRecognizer(model, RATE)
    text, start, audio = "", time.time(), bytearray()
    while time.time() - start < seconds and not STOP["v"]:
        try:
            data = q.get(timeout=0.5)
        except queue.Empty:
            continue
        audio += data
        emit("level", f"{level(data):.2f}")
        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "")
            if text:
                break
    if not text:
        text = json.loads(rec.FinalResult()).get("text", "")
    emit("level", "0")
    if text:                                   # Vosk heard speech: let Whisper get the words right
        try:
            better = transcribe(bytes(audio))
            if better:
                text = better
        except Exception:
            pass
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
        import awareness
        watcher = awareness.Watcher()
        whisper_warm()                          # Whisper loads in the background (~2s)
        import persona
        speak(persona.greeting())               # also loads the voice (~4s) before you need it
        drain(q)                                # ...and it said "Rayo": don't wake on that
        rec = wake_rec()
        while not STOP["v"]:
            try:
                data = q.get(timeout=0.5)
            except queue.Empty:
                if not mic.alive():
                    fail("microphone stopped — is a mic connected and unmuted?")
                continue
            for kind, alert in watcher.tick():      # she speaks up first (battery, heat, memory, rain)
                import persona
                alert = persona.alert(kind, alert)
                emit("alert", alert)
                notify("Rayo: " + alert)
                if not awareness.quiet_now():
                    speak(alert)
                drain(q)                            # never hear herself as a wake word
                emit("idle")
            if rec.AcceptWaveform(data) and is_wake(rec.Result()):
                chime(); emit("listening")
                brain_warm()                    # load the LLM while you speak (no-op without Ollama)
                while not q.empty():          # discard the wake phrase itself
                    try: q.get_nowait()
                    except queue.Empty: break
                report(capture(model, q), model, q)
                drain(q)                          # never hear Rayo's own voice as a wake word
                emit("idle")
                rec = wake_rec()
    emit("off")


if __name__ == "__main__":
    wake_loop() if "--wake" in sys.argv[1:] else one_shot()
