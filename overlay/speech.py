"""Rayo's voice: offline text-to-speech with Piper, played through PipeWire.

Speaker.say(text) queues a line; one worker thread synthesises and plays lines
in order, so the brain can hand over sentences while it's still thinking.
While a line plays, the audio loudness is sent to the HUD as `level`
events, so the reactor pulses with Rayo's voice.

Voices live in ~/.local/share/rayo-voice/tts/<name>.onnx (voice-setup.sh
downloads one). Turn speech on or off by voice ("stop talking" / "talk to
me"), or with {"speech": {"on": false}} in ~/.config/rayo/config.json.
"""
import os, re, time, queue, threading, subprocess
from array import array

import config

TTS_DIR = os.path.expanduser("~/.local/share/rayo-voice/tts")
DEFAULT_VOICE = "en_GB-jenny_dioco-medium"
PLAYERS = (["pw-play", "--raw", "--rate", "{rate}", "--channels", "1", "--format", "s16", "-"],
           ["paplay", "--raw", "--rate={rate}", "--channels=1", "--format=s16le"],
           ["aplay", "-q", "-t", "raw", "-r", "{rate}", "-f", "S16_LE", "-c", "1"])
FRAME = 0.08                     # seconds of audio per HUD level update


def enabled():
    return bool(config.get("speech", "on", True))


def speakable(text):
    """HUD text → something that sounds right out loud."""
    t = re.sub(r"[“”\"]", "", text or "")
    t = t.replace("°c", " degrees").replace("°C", " degrees").replace("°F", " degrees fahrenheit")
    t = re.sub(r"(\d)\s*%", r"\1 percent", t)
    t = re.sub(r"\b(\d+)h 0?(\d+)m\b", r"\1 hours \2 minutes", t)
    t = t.replace(" · ", ", ").replace("·", ",").replace("…", "").replace("—", ", ")
    t = re.sub(r"\.(md|txt|pdf|docx?|odt|xlsx?|pptx?|rtf)\b", "", t, flags=re.I)   # "readme", not "readme dot md"
    t = re.sub(r"\b[A-Z]{4,}\b", lambda m: m.group(0).lower(), t)                    # README → readme (not spelled out)
    t = re.sub(r"\bgmail\b", "g mail", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" ,")


class Speaker:
    def __init__(self, emit=lambda *a: None):
        self.emit = emit
        self.voice = None
        self.failed = False
        self.q = queue.Queue()
        self.idle = threading.Event()
        self.idle.set()
        self.proc = None
        threading.Thread(target=self._work, daemon=True).start()

    # -- loading ------------------------------------------------------------
    def available(self):
        name = config.get("speech", "voice", DEFAULT_VOICE)
        return os.path.exists(os.path.join(TTS_DIR, name + ".onnx"))

    def preload(self):
        """Load the voice in the background (~4s, ~100MB) so the first reply is instant."""
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        if self.voice or self.failed:
            return self.voice
        try:
            from piper import PiperVoice
            name = config.get("speech", "voice", DEFAULT_VOICE)
            self.voice = PiperVoice.load(os.path.join(TTS_DIR, name + ".onnx"))
        except Exception:
            self.failed = True                     # no piper / no voice: captions only
        return self.voice

    # -- speaking -----------------------------------------------------------
    def say(self, text):
        text = speakable(text)
        if text and enabled() and self.available():
            self.idle.clear()
            self.q.put(text)

    def wait(self, timeout=60):
        """Block until everything queued has been spoken."""
        self.idle.wait(timeout)

    def stop(self):
        """Cut Rayo off mid-sentence and forget anything queued."""
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def _work(self):
        while True:
            text = self.q.get()
            try:
                if self._load():
                    self._speak(text)
            except Exception:
                pass
            if self.q.empty():
                self.emit("level", "0")
                self.idle.set()

    def _speak(self, text):
        chunks = list(self.voice.synthesize(text))
        if not chunks:
            return
        rate = chunks[0].sample_rate
        audio = b"".join(c.audio_int16_bytes for c in chunks)
        for argv in PLAYERS:
            try:
                self.proc = subprocess.Popen([a.format(rate=rate) for a in argv], stdin=subprocess.PIPE,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except FileNotFoundError:
                continue
        else:
            return
        self.emit("speaking", "")
        pulse = threading.Thread(target=self._pulse, args=(audio, rate), daemon=True)
        pulse.start()
        try:
            self.proc.stdin.write(audio)
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        self.proc.wait()
        pulse.join(1)

    def _pulse(self, audio, rate):
        """Stream the voice's loudness to the HUD in step with playback."""
        samples = array("h", audio)
        n = int(rate * FRAME)
        start = time.time()
        for i in range(0, len(samples), n):
            if self.proc.poll() is not None:
                break
            frame = samples[i:i + n]
            rms = (sum(s * s for s in frame[::4]) / max(1, len(frame[::4]))) ** 0.5
            self.emit("level", f"{min(1.0, rms / 9000):.2f}")
            time.sleep(max(0, start + (i + n) / rate - time.time()))


class Sentences:
    """Feed it the brain's growing answer; it speaks each sentence as soon as it's complete."""
    def __init__(self, speaker):
        self.speaker, self.done = speaker, 0

    def feed(self, text):
        base = self.done
        for m in re.finditer(r".+?[.!?](?=\s|$)", text[base:]):
            if base + m.end() < len(text):              # more text follows, so the sentence is finished
                self.speaker.say(m.group(0))
                self.done = base + m.end()

    def finish(self, text):
        rest = text[self.done:].strip() if text.startswith(text[:self.done]) else text
        if rest:
            self.speaker.say(rest)
