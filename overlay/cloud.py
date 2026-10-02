"""Rayo's cloud brain: Claude Haiku through the Anthropic API, with your own API key.

Why an API key and not your Claude subscription: Anthropic's rules say products should use API keys, and
only Anthropic's own apps may use subscription logins. A key also keeps Rayo's spending separate from your
coding limits, and you can cap it in the Anthropic Console.

The chain for any question that reaches the brain:
    learned answers (Learned.md, instant, free, offline)
      -> Claude Haiku (smart; needs internet and a key)
      -> the small local model (offline fallback, helped by saved answers as examples)

Privacy: only your question and the last couple of exchanges leave the laptop. Never your vault, your
memories, your battery or your files. Questions that need your own memories (a fact you told her) stay local,
unless you set {"cloud": {"share_memory": true}}. The HUD says ASKING CLAUDE whenever it happens.

Settings (~/.config/rayo/config.json), all optional:
  {"cloud": {"mode": "auto",                 // auto | always | off  (voice: "use Claude", "stay offline")
             "model": "claude-haiku-4-5",
             "monthly_cap_usd": 3.0, "daily_limit": 150, "share_memory": false}}
The key lives in ~/.config/rayo/anthropic.key (chmod 600; made by ./set-claude-key.sh) or ANTHROPIC_API_KEY.
"""
import os, re, time

import config

KEY_FILE = os.path.expanduser("~/.config/rayo/anthropic.key")
API_URL = "https://api.anthropic.com"          # pinned: a stray ANTHROPIC_BASE_URL (e.g. pointing at Ollama) must not hijack us
DEFAULT_MODEL = "claude-haiku-4-5"
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}   # $ per million tokens (in, out)
MAX_TOKENS = 300                                # spoken answers are short
HISTORY_TURNS, HISTORY_TTL = 3, 300
SYSTEM = (
    "You are Rayo (Radiant Assistant, Your Oracle), a voice assistant living on {user}'s laptop. Your reply is "
    "spoken aloud, so answer in one to three short sentences, under 50 words, as plain text: no markdown, no "
    "lists, no emoji. The user's words come from speech recognition and may be slightly misheard; answer what "
    "they most likely meant. Never repeat the question back. If you don't know, say so in one short sentence. "
    "You cannot control the computer. Answer plainly; a separate system adds personality. It is {time} on {date}. {soul}"
)
STARTERS = re.compile(r"^(explain|why|how|compare|write|summari[sz]e|translate|recommend|define|describe|what('?s| is| are| was| were)|"
                      r"who|when|where|which|should|is it|are there|can you tell|give me|help me|suggest|difference)\b", re.I)
_state = {"client": None, "key": None, "history": [], "last": 0.0}


# ---- key, mode, budget ---------------------------------------------------------------
def api_key():
    """The key from the private file, else ANTHROPIC_API_KEY, but only if it looks real:
    another tool may have exported a placeholder (e.g. for a local model server)."""
    try:
        if os.stat(KEY_FILE).st_mode & 0o077:        # readable by others? lock it down
            os.chmod(KEY_FILE, 0o600)
        with open(KEY_FILE) as f:
            k = f.read().strip()
        if k.startswith("sk-ant-"):
            return k
    except OSError:
        pass
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return k if k.startswith("sk-ant-") else None


def mode():
    m = str(config.get("cloud", "mode", "auto")).lower()
    return m if m in ("auto", "always", "off") else "auto"


def model():
    return config.get("cloud", "model", DEFAULT_MODEL)


def _usage():
    s = dict(config.load().get("cloud", {}).get("usage", {}))
    month, day = time.strftime("%Y-%m"), time.strftime("%Y-%m-%d")
    if s.get("month") != month:
        s.update(month=month, tin=0, tout=0, calls=0)
    if s.get("day") != day:
        s.update(day=day, day_calls=0)
    return s


def record(tokens_in, tokens_out):
    s = _usage()
    s.update(tin=s.get("tin", 0) + tokens_in, tout=s.get("tout", 0) + tokens_out,
             calls=s.get("calls", 0) + 1, day_calls=s.get("day_calls", 0) + 1)
    cfg = config.load().get("cloud", {})
    cfg["usage"] = s
    config.update("cloud", cfg)


def cost_usd(s=None):
    s = s or _usage()
    pin, pout = PRICES.get(model(), PRICES[DEFAULT_MODEL])
    return s.get("tin", 0) * pin / 1e6 + s.get("tout", 0) * pout / 1e6


def over_budget():
    s = _usage()
    return cost_usd(s) >= float(config.get("cloud", "monthly_cap_usd", 3.0)) or s.get("day_calls", 0) >= int(config.get("cloud", "daily_limit", 150))


def usage_text():
    s = _usage()
    n, c = s.get("calls", 0), cost_usd(s)
    if not n:
        return "Claude hasn't answered anything this month, so it's cost you nothing."
    cents = c * 100
    cost = f"about {cents:.1f} cents" if cents < 100 else f"about {c:.2f} dollars"
    cap = float(config.get("cloud", "monthly_cap_usd", 3.0))
    return f"Claude has answered {n} question{'' if n == 1 else 's'} this month for {cost}. Your monthly cap is {cap:.0f} dollars."


def why_not():
    """A spoken reason Claude can't be used right now, or None if it can."""
    if mode() == "off":
        return "Claude is switched off. Say 'use Claude' to turn it back on."
    if not api_key():
        return "I don't have a Claude key yet. Run set-claude-key in the Rayo folder to add one."
    if over_budget():
        return "I've reached this month's Claude spending limit, so I'm sticking to my small brain."
    try:
        import anthropic  # noqa: F401
    except Exception:
        return "The Anthropic library isn't installed. Run voice-setup to add it."
    return None


def available():
    return why_not() is None


# ---- routing -------------------------------------------------------------------------
def _personal(question):
    """Does answering need something you told her (a fact in your vault)? Then Claude can't help and it stays local."""
    try:
        import memory
        return bool(memory.relevant(question)) and not config.get("cloud", "share_memory", False)
    except Exception:
        return False


def want_cloud(question, force=False):
    if force:
        return True
    if mode() == "off" or _personal(question):
        return False
    if mode() == "always":
        return True
    return len(question.split()) >= 5 or bool(STARTERS.match(question.strip()))


def decide(question, force=False):
    """Where this question will go, so the HUD can say so before it starts: 'learned' | 'claude' | 'local'."""
    import learned
    if not force and learned.lookup(question):
        return "learned"
    return "claude" if want_cloud(question, force) and available() else "local"


# ---- asking Claude -------------------------------------------------------------------
def _client():
    key = api_key()
    if _state["client"] is None or _state["key"] != key:
        import anthropic
        # explicit key AND base_url: ignore ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN left in the environment
        _state["client"] = anthropic.Anthropic(api_key=key, base_url=API_URL, max_retries=1, timeout=25.0)
        _state["key"] = key
    return _state["client"]


def _messages(question):
    if time.time() - _state["last"] > HISTORY_TTL:
        _state["history"].clear()
    return _state["history"] + [{"role": "user", "content": question}]


def ask_claude(question, on_text=None):
    """Stream an answer from Claude. Returns the text. Raises the SDK's typed errors for think() to handle."""
    try:
        import soul
        soul_line = soul.prompt()
    except Exception:
        soul_line = ""
    system = SYSTEM.format(user=os.environ.get("USER", "the user"), time=time.strftime("%-I:%M %p"),
                           date=time.strftime("%A %d %B %Y"), soul=soul_line)
    msgs, text, shown = _messages(question), "", 0.0
    with _client().messages.stream(model=model(), max_tokens=MAX_TOKENS, system=system, messages=msgs) as stream:
        for piece in stream.text_stream:
            text += piece
            if on_text and time.time() - shown > 0.25:
                shown = time.time()
                on_text(re.sub(r"[*_#`>]+", "", text).strip())
        final = stream.get_final_message()
    record(final.usage.input_tokens, final.usage.output_tokens)
    text = re.sub(r"\s+", " ", re.sub(r"[*_#`>]+", "", text)).strip()
    _state["history"] += [{"role": "user", "content": question}, {"role": "assistant", "content": text}]
    del _state["history"][:-HISTORY_TURNS * 2]
    _state["last"] = time.time()
    return text


def think(question, on_text=None, force=False):
    """Answer a question: learned -> Claude -> local. Returns (text, source) with source in
    'learned' | 'claude' | 'local' | 'notice' (a spoken explanation, e.g. the key was rejected)."""
    import learned
    if not force:
        hit = learned.lookup(question)
        if hit:
            return hit, "learned"
    if want_cloud(question, force):
        reason = why_not()
        if reason is None:
            try:
                text = ask_claude(question, on_text)
                if text:
                    learned.save(question, text)
                    return text, "claude"
            except Exception as e:                                  # most specific first (see the SDK's error docs)
                import anthropic
                if isinstance(e, anthropic.AuthenticationError):
                    return "My Claude key was rejected. Check it with set-claude-key.", "notice"
                if isinstance(e, anthropic.PermissionDeniedError):
                    return "My Claude key doesn't have permission. Check it in the Anthropic Console.", "notice"
                if isinstance(e, anthropic.NotFoundError):
                    return "I couldn't find that Claude model. Check the model name in my settings.", "notice"
                # rate limit, overloaded, offline, timeout...: quietly fall back to the small brain
        elif force:
            return reason, "notice"
    import brain
    return brain.ask(question, on_text, examples=learned.similar(question)), "local"
