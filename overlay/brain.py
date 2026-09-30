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
KEEP_ALIVE = "10m"             # stays loaded 10 min after the last question (reloading costs ~10-20s)
MEMORY_TURNS = 3                 # remember the last 3 exchanges ("and how old is he?")
MEMORY_TTL = 300                 # forget the conversation after 5 quiet minutes
SYSTEM = (
    "You are Rayo (Radiant Assistant, Your Oracle), the voice assistant on {user}'s Linux laptop. "
    "Your reply is shown under a HUD reactor and spoken aloud, so answer in one or two short "
    "sentences, under 40 words, plain text, no markdown, no lists, no emoji. "
    "The user's words come from speech recognition and may be slightly misheard; answer what "
    "they most likely meant. Never repeat the user's words back as your answer. "
    "If you don't know something, or it needs live data you don't have, say so in one short sentence. "
    "You cannot control the computer yourself. It is {time} on {date}. {live}"
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


def _live():
    """A line of live facts from the HUD's own stats (weather, battery) so answers can use them."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "hud", "stats.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return ""
    bits = []
    if d.get("wx_cond"):
        bits.append(f"Weather outside now: {d.get('wx_temp', '').lstrip('+')}, {d['wx_cond'].lower()}.")
    if d.get("battery") is not None:
        bits.append(f"Laptop battery: {d['battery']}% ({d.get('batt_status', '').lower()}).")
    return " ".join(bits)


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
    system = SYSTEM.format(user=os.environ.get("USER", "the user"), date=time.strftime("%A %d %B %Y"),
                           time=time.strftime("%-I:%M %p"), live=_live())
    try:
        import memory
        known = memory.relevant(question)
    except Exception:
        known = []
    if known:                                   # facts from the Obsidian vault ("remember that …")
        system += ("\nThings the user told you to remember (\"I\"/\"my\" means the user). Use them when relevant:\n- "
                   + "\n- ".join(known))
    msgs = [{"role": "system", "content": system}]
    msgs += _history + [{"role": "user", "content": question}]
    body = {"model": m, "messages": msgs, "stream": True, "think": False, "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": 2048, "num_predict": 110, "temperature": 0.6}}
    out, shown = "", 0.0
    try:
        # per-read timeout: covers a cold load on a busy, swapping laptop
        with _req("/api/chat", body, timeout=60) as r:
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
            return "I'm thinking too slowly right now, the laptop is short on memory. try again in a moment"
        return f"my brain didn't answer ({e.__class__.__name__})"
    answer = _clean(out) or "I don't have an answer for that."
    _history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
    del _history[:-MEMORY_TURNS * 2]
    _last[0] = time.time()
    return answer


ACTION = re.compile(r"\b(open|launch|start|run|go to|show|find|search|look up|google|check|play|pause|skip|next|previous|"
                    r"volume|louder|quieter|mute|unmute|remember|note|weather|rain|battery|status|take me)\b", re.I)
TOOL_RULES = (" You can also use tools to act on the laptop. Use a tool only when the user asks you to DO something "
              "(open, search, check, play, remember). For questions and chat, just answer in words. "
              "Pick the tool by what they want: apps, folders, files and websites all use open. "
              "You have no tool for power, deleting, sending or settings, so refuse those politely.")


def wants_action(q):
    """Only offer tools when the request sounds like an action; a 1.7B model given tools for
    'why is the sky blue' may call one anyway."""
    return bool(ACTION.search(q))


def act(question, on_text=None):
    """Like ask(), but the model may call Rayo's tools (tools.py). Returns
    {"text": answer, "calls": [...]}: run the calls, or speak the text."""
    import tools
    m = model()
    if not m:
        return {"text": ask(question, on_text), "calls": []}
    if not wants_action(question):
        return {"text": ask(question, on_text), "calls": []}
    if time.time() - _last[0] > MEMORY_TTL:
        _history.clear()
    system = SYSTEM.format(user=os.environ.get("USER", "the user"), date=time.strftime("%A %d %B %Y"),
                           time=time.strftime("%-I:%M %p"), live=_live()) + TOOL_RULES
    try:
        import memory
        known = memory.relevant(question)
    except Exception:
        known = []
    if known:
        system += "\nThings the user told you to remember:\n- " + "\n- ".join(known)
    body = {"model": m, "messages": [{"role": "system", "content": system}] + _history
            + [{"role": "user", "content": question}], "tools": tools.schema(), "stream": False, "think": False,
            "keep_alive": KEEP_ALIVE, "options": {"num_ctx": 2048, "num_predict": 160, "temperature": 0.2}}
    try:
        with _req("/api/chat", body, timeout=60) as r:
            msg = json.load(r).get("message", {})
    except OSError as e:
        return {"text": "I'm thinking too slowly right now, the laptop is short on memory. try again in a moment"
                if "timed out" in str(e) else f"my brain didn't answer ({e.__class__.__name__})", "calls": []}
    calls = msg.get("tool_calls") or []
    if not calls and "<tool_call>" in (msg.get("content") or ""):          # older templates print the call as text
        calls = [{"function": c} for c in _text_calls(msg["content"])]
    text = _clean(msg.get("content", ""))
    _last[0] = time.time()
    if not calls:
        _history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": text or "I don't have an answer for that."}])
        del _history[:-MEMORY_TURNS * 2]
    return {"text": text or "I don't have an answer for that.", "calls": calls}


def _text_calls(content):
    out = []
    for blob in re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, flags=re.S):
        try:
            out.append(json.loads(blob))
        except ValueError:
            pass
    return out


if __name__ == "__main__":                                  # python3 brain.py "why is the sky blue"
    import sys
    print("model:", model())
    print(ask(" ".join(sys.argv[1:]) or "who are you?", lambda t: print("…", t)))
