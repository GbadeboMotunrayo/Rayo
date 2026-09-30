"""Rayo's brain: a small local LLM via Ollama, used only when no command matches.

Offline and private: talks to Ollama on 127.0.0.1 only. The brain can talk,
never act: commands come from commands.py, so a model mistake can't touch
the machine.

Model choice: $RAYO_BRAIN_MODEL, else ~/.config/rayo/config.json
{"brain": {"model": "..."}}, else the first installed model from PREFERRED,
else whatever Ollama has installed. It stays loaded KEEP_ALIVE after the last
question, then Ollama frees the memory.
"""
import os, re, json, time, threading, urllib.request

OLLAMA = os.environ.get("RAYO_OLLAMA", "http://127.0.0.1:11434")
PREFERRED = ("gemma3:1b", "gemma3:1b-it-qat", "qwen3:1.7b", "llama3.2:1b")
KEEP_ALIVE = "3m"
MEMORY_TURNS = 3                 # remember the last 3 exchanges ("and how old is he?")
MEMORY_TTL = 300                 # forget the conversation after 5 quiet minutes
SYSTEM = (
    "You are Rayo (Radiant Assistant, Your Oracle), the voice assistant on {user}'s Linux laptop. "
    "Your reply is shown under a HUD reactor and may be spoken aloud, so answer in one or two "
    "short sentences, under 40 words, plain text, no markdown, no lists, no emoji. "
    "The user's words come from offline speech recognition and may be misheard; answer what "
    "they most likely meant. If you truly don't know, say so briefly. "
    "You cannot open apps or change settings yourself; if asked, say which command to say "
    "(for example: say 'open browser'). Today is {date}."
)

_history, _last = [], [0.0]


def _req(path, body=None, timeout=5):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(OLLAMA + path, data=data, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(r, timeout=timeout)


def _config_model():
    import config
    return config.get("brain", "model")


def model():
    """The model to use, or None if Ollama isn't running / has no models."""
    want = os.environ.get("RAYO_BRAIN_MODEL") or _config_model()
    try:
        with _req("/api/tags") as r:
            names = [m["name"] for m in json.load(r).get("models", [])]
    except OSError:
        return None
    if want:
        return want if any(n == want or n.split(":")[0] == want for n in names) else None
    for p in PREFERRED:
        if p in names:
            return p
    chat = [n for n in names if "embed" not in n]          # skip embedding-only models
    return chat[0] if chat else None


def warm():
    """Load the model in the background (called on the wake word), so the first
    answer doesn't wait ~10s for it to come off disk."""
    def go():
        m = model()
        if m:
            try:
                _req("/api/generate", {"model": m, "keep_alive": KEEP_ALIVE}, timeout=60).read()
            except OSError:
                pass
    threading.Thread(target=go, daemon=True).start()


def _clean(text):
    text = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S)   # older Ollama ignores think:false
    text = re.sub(r"[*_#`>]+", "", text)                             # stray markdown
    return re.sub(r"\s+", " ", text).strip()


def ask(question, on_text=None):
    """Answer a question. on_text(partial) is called as words stream in.
    Returns the full answer, or a short message saying why there isn't one."""
    m = model()
    if not m:
        return "my brain is offline. install ollama and pull a model, e.g. ollama pull gemma3:1b"
    if time.time() - _last[0] > MEMORY_TTL:
        _history.clear()
    msgs = [{"role": "system", "content": SYSTEM.format(
        user=os.environ.get("USER", "the user"), date=time.strftime("%A %d %B %Y"))}]
    msgs += _history + [{"role": "user", "content": question}]
    body = {"model": m, "messages": msgs, "stream": True, "think": False, "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": 2048, "num_predict": 110, "temperature": 0.6}}
    out, shown = "", 0.0
    try:
        # timeout is per read: a queued request (Ollama serves one at a time on CPU) fails fast
        with _req("/api/chat", body, timeout=25) as r:
            for line in r:
                chunk = json.loads(line)
                out += chunk.get("message", {}).get("content", "")
                if on_text and time.time() - shown > 0.25:          # ~4 HUD updates a second
                    shown = time.time()
                    on_text(_clean(out))
                if chunk.get("done"):
                    break
    except OSError as e:
        if not out and isinstance(e, TimeoutError) or "timed out" in str(e):
            return "my brain is busy with another app right now. try again in a moment"
        return f"my brain didn't answer ({e.__class__.__name__})"
    answer = _clean(out) or "I don't have an answer for that."
    _history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
    del _history[:-MEMORY_TURNS * 2]
    _last[0] = time.time()
    return answer


if __name__ == "__main__":                                  # python3 brain.py "why is the sky blue"
    import sys
    print("model:", model())
    print(ask(" ".join(sys.argv[1:]) or "who are you?", lambda t: print("…", t)))
