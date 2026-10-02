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
    "You cannot control the computer yourself. It is {time} on {date}. {live} {persona} {soul}"
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


def _soul():
    try:
        import soul
        return soul.prompt()
    except Exception:
        return ""


def _persona():
    try:
        import persona
        return persona.prompt()
    except Exception:
        return ""


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


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")


def _clean(text):
    text = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S)   # older Ollama ignores think:false
    text = EMOJI.sub("", text)                                       # she's spoken aloud: no emoji
    text = re.sub(r"[*_#`>]+", "", text)                             # stray markdown
    return re.sub(r"\s+", " ", text).strip()


def ask(question, on_text=None, examples=None):
    """Answer a question. on_text(partial) is called as words stream in.
    Returns the full answer, or a short message saying why there isn't one."""
    m = model()
    if not m:
        return "my brain is offline. install ollama and pull a model, e.g. ollama pull gemma3:1b"
    if time.time() - _last[0] > MEMORY_TTL:
        _history.clear()
    system = SYSTEM.format(user=os.environ.get("USER", "the user"), date=time.strftime("%A %d %B %Y"),
                           time=time.strftime("%-I:%M %p"), live=_live(), persona=_persona(), soul=_soul())
    try:
        import memory
        known = memory.relevant(question)
    except Exception:
        known = []
    if known:                                   # facts from the Obsidian vault ("remember that …")
        system += ("\nThings the user told you to remember (\"I\"/\"my\" means the user). Use them when relevant:\n- "
                   + "\n- ".join(known))
    if examples:                                # answers Claude gave to similar questions: the small model learns from them
        system += "\nGood answers you gave before to similar questions:\n" + "\n".join(f"Q: {q}\nA: {a}" for q, a in examples)[:700]
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
TOOL_RULES = (
    " You can act on the laptop by choosing tools. First decide do_it: true if the user asks you to DO something "
    "(open, find, search, check, play, remember), false for questions and chat. You CAN open apps, folders, files and "
    "websites: never say you can't. Tools (arg in brackets):\n"
    "- open [what to open]\n- search_web [search words]\n- weather [now, today, tonight or tomorrow]\n"
    "- remember [the fact, in the user's words]\n- recall []\n- battery []\n- status []\n"
    "- volume [up, down, mute or unmute]\n- media [play_pause, next or previous]\n"
    "You have no tool for power, deleting, sending or settings.\n"
    "Examples:\n"
    "user: turn it up a bit -> do_it true, calls: volume up\n"
    "user: next track please -> do_it true, calls: media next\n"
    "user: take me to netflix -> do_it true, calls: open netflix\n"
    "user: pull up the tech folder -> do_it true, calls: open tech folder\n"
    "user: what's the forecast for tomorrow -> do_it true, calls: weather tomorrow\n"
    "user: what have i asked you to remember -> do_it true, calls: recall\n"
    "user: how are my system resources -> do_it true, calls: status\n"
    "user: open chrome and search for cheap flights -> do_it true, calls: open chrome; search_web cheap flights\n"
    "user: remember that tolu's birthday is in may -> do_it true, calls: remember tolu's birthday is in may\n"
    "user: how old is the universe -> do_it false, calls: none, reply: about 13.8 billion years.")
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "do_it": {"type": "boolean"},
        "calls": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
            "tool": {"type": "string", "enum": ["open", "search_web", "weather", "remember", "recall", "battery",
                                               "status", "volume", "media"]},
            "arg": {"type": "string"}}, "required": ["tool", "arg"]}},
        "reply": {"type": "string"}},
    "required": ["do_it", "calls", "reply"]}
ARG_KEY = {"open": "target", "search_web": "query", "weather": "when", "remember": "fact", "volume": "action", "media": "action"}


CLAIMS = re.compile(r"\b(will be|i'?ll|i will|has been|have been|is being|opened|opening|done|sent|deleted|shutting|shut down|"
                    r"turned|turning|i can'?t|i cannot|sorry)\b|^(shutting|deleting|sending|opening|playing|skipping|turning|launching|"
                    r"searching|closing|restarting|muting|pausing)\b", re.I)


def tools_enabled():
    """Model tool-use is OFF by default: Qwen 1.7B picked the right tool for only 12 of 20 test phrases and sometimes
    claimed actions it never took. Rules (commands.py) handle the common cases. Turn on with
    {"brain": {"tools": true}} once you run a stronger model."""
    import config
    return bool(config.get("brain", "tools", False))


def wants_action(q):
    """Only offer tools when the request sounds like an action; a 1.7B model given tools for
    'why is the sky blue' may call one anyway."""
    return bool(ACTION.search(q))


def act(question, on_text=None):
    """Like ask(), but the model may choose Rayo's tools (tools.py). The model is forced to answer in a fixed
    JSON shape, so it can only name a real tool (native tool-calling is unreliable on small models).
    Returns {"text": answer, "calls": [...]}: run the calls, or speak the text."""
    m = model()
    if not m or not wants_action(question):
        return {"text": ask(question, on_text), "calls": []}
    if time.time() - _last[0] > MEMORY_TTL:
        _history.clear()
    system = SYSTEM.format(user=os.environ.get("USER", "the user"), date=time.strftime("%A %d %B %Y"),
                           time=time.strftime("%-I:%M %p"), live=_live(), persona=_persona(), soul=_soul()) + TOOL_RULES
    try:
        import memory
        known = memory.relevant(question)
    except Exception:
        known = []
    if known:
        system += "\nThings the user told you to remember:\n- " + "\n- ".join(known)
    body = {"model": m, "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
            "format": PLAN_SCHEMA, "stream": False, "think": False, "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": 2048, "num_predict": 200, "temperature": 0}}
    try:
        with _req("/api/chat", body, timeout=60) as r:
            raw = json.load(r).get("message", {}).get("content", "")
        plan = json.loads(raw)
    except (OSError, ValueError) as e:
        return {"text": "I'm thinking too slowly right now, the laptop is short on memory. try again in a moment"
                if isinstance(e, OSError) else "I didn't quite get that. try again", "calls": []}
    calls = []
    for c in plan.get("calls", [])[:3]:
        name, arg = c.get("tool"), str(c.get("arg", "")).strip()
        calls.append({"function": {"name": name, "arguments": {ARG_KEY[name]: arg} if name in ARG_KEY else {}}})
    text = _clean(plan.get("reply", ""))
    _last[0] = time.time()
    if not calls and (not text or CLAIMS.search(text)):
        # it didn't pick a tool, and what it said claims an action happened (nothing did): answer normally instead
        return {"text": ask(question, on_text), "calls": []}
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
