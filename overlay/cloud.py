"""Rayo's cloud brain: Groq every day, Claude when you ask, your own API keys.

Two providers, one chain. For any question that reaches the brain:
    learned answers (Learned.md: instant, free, offline)
      -> your everyday cloud brain (Groq's gpt-oss-20b: fast, free plan, no card)
      -> the small local model (offline fallback, helped by saved answers as examples)
"Ask Claude ..." sends that one question to Claude Haiku instead (if you added a Claude key).

Why API keys: providers' rules say products should use API keys (Anthropic does not allow subscription
logins in other apps), and a key keeps Rayo's spending separate from anything else you use.

Privacy: only your question and the last couple of exchanges leave the laptop. Never your vault, memories,
battery or files. Questions that need something you told her stay local, unless {"cloud": {"share_memory": true}}.
The HUD just says THINKING; the daily note in your vault records which brain answered. Groq's docs say it doesn't retain requests by
default (troubleshooting logs up to 30 days, switchable off in its Console); free-tier terms at Google are why
Gemini was not the pick.

Settings (~/.config/rayo/config.json), all optional:
  {"cloud": {"mode": "auto",                       // auto | always | off   (voice: "use the cloud", "stay offline")
             "provider": "groq",                   // the everyday one: groq | anthropic
             "models": {"groq": "openai/gpt-oss-20b", "anthropic": "claude-haiku-4-5"},
             "groq_paid": false,                   // true if you moved Groq to a paid plan (so spend is tracked)
             "monthly_cap_usd": 3.0, "daily_limit": 150, "share_memory": false}}
Keys: ./set-key.sh groq  and  ./set-key.sh claude   (files in ~/.config/rayo/, chmod 600; or GROQ_API_KEY / ANTHROPIC_API_KEY).
"""
import os, re, time

import config

CONF = os.path.expanduser("~/.config/rayo")
PROVIDERS = {
    "groq": {"label": "Groq", "key_file": os.path.join(CONF, "groq.key"), "env": "GROQ_API_KEY", "model": "openai/gpt-oss-20b",
             "base_url": "https://api.groq.com", "price": (0.075, 0.30), "free_plan": True},
    "anthropic": {"label": "Claude", "key_file": os.path.join(CONF, "anthropic.key"), "env": "ANTHROPIC_API_KEY",
                  "model": "claude-haiku-4-5", "base_url": "https://api.anthropic.com", "price": (1.0, 5.0), "free_plan": False},
}
PRICES = {"openai/gpt-oss-20b": (0.075, 0.30), "openai/gpt-oss-120b": (0.15, 0.60), "claude-haiku-4-5": (1.0, 5.0),
          "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}       # $ per million tokens (in, out)
MAX_TOKENS = 300                                # spoken answers are short
GROQ_MAX_TOKENS = 700                           # gpt-oss "reasoning" tokens count against the completion budget
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
_state = {"clients": {}, "history": [], "last": 0.0}


# ---- keys, mode, providers ----------------------------------------------------------------
def _valid_key(provider, k):
    if provider == "anthropic":
        return k.startswith("sk-ant-")
    return len(k) >= 24 and re.fullmatch(r"[A-Za-z0-9_\-]+", k) is not None       # groq keys are gsk_...; reject short placeholders


def api_key(provider):
    """The key from its private file, else the environment, but only if it looks real: another tool may
    have exported a placeholder (e.g. for a local model server)."""
    p = PROVIDERS[provider]
    try:
        if os.stat(p["key_file"]).st_mode & 0o077:      # readable by others? lock it down
            os.chmod(p["key_file"], 0o600)
        with open(p["key_file"]) as f:
            k = f.read().strip()
        if _valid_key(provider, k):
            return k
    except OSError:
        pass
    k = os.environ.get(p["env"], "").strip()
    return k if _valid_key(provider, k) else None


def mode():
    m = str(config.get("cloud", "mode", "auto")).lower()
    return m if m in ("auto", "always", "off") else "auto"


def model(provider):
    return (config.get("cloud", "models", {}) or {}).get(provider) or PROVIDERS[provider]["model"]


def everyday():
    """The provider used for normal questions: the configured one if it has a key, else any provider with a key."""
    want = config.get("cloud", "provider", "groq")
    for prov in [want] + [p for p in PROVIDERS if p != want]:
        if prov in PROVIDERS and api_key(prov):
            return prov
    return want if want in PROVIDERS else "groq"


# ---- usage and budget ------------------------------------------------------------------------
def _usage(provider):
    s = dict((config.load().get("cloud", {}).get("usage", {}) or {}).get(provider, {}))
    month, day = time.strftime("%Y-%m"), time.strftime("%Y-%m-%d")
    if s.get("month") != month:
        s.update(month=month, tin=0, tout=0, calls=0)
    if s.get("day") != day:
        s.update(day=day, day_calls=0)
    return s


def record(provider, tokens_in, tokens_out):
    s = _usage(provider)
    s.update(tin=s.get("tin", 0) + tokens_in, tout=s.get("tout", 0) + tokens_out,
             calls=s.get("calls", 0) + 1, day_calls=s.get("day_calls", 0) + 1)
    cfg = config.load().get("cloud", {})
    usage = dict(cfg.get("usage", {}) or {})
    usage[provider] = s
    cfg["usage"] = usage
    config.update("cloud", cfg)


def cost_usd(provider):
    """Real spend. Groq on its free plan costs nothing (set groq_paid once you upgrade)."""
    if PROVIDERS[provider]["free_plan"] and not config.get("cloud", "groq_paid", False):
        return 0.0
    s = _usage(provider)
    pin, pout = PRICES.get(model(provider), PROVIDERS[provider]["price"])
    return s.get("tin", 0) * pin / 1e6 + s.get("tout", 0) * pout / 1e6


def total_cost():
    return sum(cost_usd(p) for p in PROVIDERS)


def over_budget(provider):
    return (total_cost() >= float(config.get("cloud", "monthly_cap_usd", 3.0))
            or _usage(provider).get("day_calls", 0) >= int(config.get("cloud", "daily_limit", 150)))


def usage_text():
    bits = []
    for prov, p in PROVIDERS.items():
        s = _usage(prov)
        n = s.get("calls", 0)
        if not n:
            continue
        c = cost_usd(prov)
        price = "free" if c == 0 else (f"about {c * 100:.1f} cents" if c < 1 else f"about {c:.2f} dollars")
        bits.append(f"{p['label']} answered {n} question{'' if n == 1 else 's'} this month ({price})")
    if not bits:
        return "The cloud hasn't answered anything this month, so it's cost you nothing."
    return ". ".join(bits) + f". Your monthly cap is {float(config.get('cloud', 'monthly_cap_usd', 3.0)):.0f} dollars."


def why_not(provider=None):
    """A spoken reason the cloud can't be used right now, or None if it can."""
    provider = provider or everyday()
    p = PROVIDERS[provider]
    if mode() == "off":
        return "The cloud is switched off. Say 'use the cloud' to turn it back on."
    if not api_key(provider):
        name = "claude" if provider == "anthropic" else provider
        return f"I don't have a {p['label']} key yet. Run set-key {name} in the Rayo folder to add one."
    if total_cost() >= float(config.get("cloud", "monthly_cap_usd", 3.0)):
        return "I've reached this month's cloud spending limit, so I'm sticking to my small brain."
    if over_budget(provider):
        return "I've used up today's cloud questions, so I'm sticking to my small brain until tomorrow."
    try:
        __import__("groq" if provider == "groq" else "anthropic")
    except Exception:
        return f"The {p['label']} library isn't installed. Run voice-setup to add it."
    return None


def available(provider=None):
    return why_not(provider) is None


# ---- routing ---------------------------------------------------------------------------------------
def _personal(question):
    """Does answering need something you told her (a fact in your vault)? Then the cloud can't help: stay local."""
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


def decide(question, force=False, provider=None):
    """Where this question will go, so the HUD can say so before it starts:
    'learned' | 'cloud:groq' | 'cloud:anthropic' | 'local'."""
    import learned
    if not force and learned.lookup(question):
        return "learned"
    prov = provider or everyday()
    return f"cloud:{prov}" if want_cloud(question, force) and available(prov) else "local"


# ---- asking -----------------------------------------------------------------------------------------
def _client(provider):
    key = api_key(provider)
    cached = _state["clients"].get(provider)
    if cached is None or cached[0] != key:
        p = PROVIDERS[provider]
        if provider == "groq":
            import groq
            # explicit key AND base_url: ignore GROQ_BASE_URL / other env left over from another tool
            c = groq.Groq(api_key=key, base_url=p["base_url"], max_retries=1, timeout=25.0)
        else:
            import anthropic
            c = anthropic.Anthropic(api_key=key, base_url=p["base_url"], max_retries=1, timeout=25.0)
        cached = _state["clients"][provider] = (key, c)
    return cached[1]


def _system():
    try:
        import soul
        soul_line = soul.prompt()
    except Exception:
        soul_line = ""
    return SYSTEM.format(user=os.environ.get("USER", "the user"), time=time.strftime("%-I:%M %p"),
                         date=time.strftime("%A %d %B %Y"), soul=soul_line)


def _clean(text):
    return re.sub(r"\s+", " ", re.sub(r"[*_#`>]+", "", text)).strip()


def ask_provider(provider, question, on_text=None):
    """Stream an answer. Returns the text. Raises the SDK's typed errors for think() to handle."""
    if time.time() - _state["last"] > HISTORY_TTL:
        _state["history"].clear()
    msgs = _state["history"] + [{"role": "user", "content": question}]
    system, text, shown, usage = _system(), "", 0.0, None
    if provider == "anthropic":
        with _client("anthropic").messages.stream(model=model("anthropic"), max_tokens=MAX_TOKENS, system=system,
                                                   messages=msgs) as stream:
            for piece in stream.text_stream:
                text += piece
                if on_text and time.time() - shown > 0.25:
                    shown = time.time(); on_text(_clean(text))
            final = stream.get_final_message()
        usage = (final.usage.input_tokens, final.usage.output_tokens)
    else:
        m = model("groq")
        extra = {"reasoning_effort": "low", "include_reasoning": False} if m.startswith("openai/gpt-oss") else {}
        stream = _client("groq").chat.completions.create(
            model=m, messages=[{"role": "system", "content": system}] + msgs, stream=True,
            max_completion_tokens=GROQ_MAX_TOKENS, temperature=0.5, **extra)
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                text += chunk.choices[0].delta.content
                if on_text and time.time() - shown > 0.25:
                    shown = time.time(); on_text(_clean(text))
            u = getattr(getattr(chunk, "x_groq", None), "usage", None) or getattr(chunk, "usage", None)
            if u:
                usage = (getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
        if usage is None:                                         # no usage block: estimate (~4 characters per token)
            usage = (len(system + "".join(x["content"] for x in msgs)) // 4, len(text) // 4)
    record(provider, *usage)
    text = _clean(text)
    _state["history"] += [{"role": "user", "content": question}, {"role": "assistant", "content": text}]
    del _state["history"][:-HISTORY_TURNS * 2]
    _state["last"] = time.time()
    return text


def _notice_for(provider, e):
    """A spoken message for errors the user must act on, or None to fall back quietly (offline, rate limit, overload...)."""
    sdk = __import__("groq" if provider == "groq" else "anthropic")
    label = PROVIDERS[provider]["label"]
    name = "claude" if provider == "anthropic" else provider
    if isinstance(e, sdk.AuthenticationError):
        return f"My {label} key was rejected. Check it with set-key {name}."
    if isinstance(e, sdk.PermissionDeniedError):
        return f"My {label} key doesn't have permission. Check it in the {label} console."
    if isinstance(e, sdk.NotFoundError):
        return f"I couldn't find that {label} model. Check the model name in my settings."
    return None


def think(question, on_text=None, force=False, provider=None):
    """Answer a question: learned -> cloud -> local. Returns (text, source) with source in
    'learned' | 'groq' | 'anthropic' | 'local' | 'notice' (a spoken explanation, e.g. a key was rejected)."""
    import learned
    if not force and provider is None:
        hit = learned.lookup(question)
        if hit:
            return hit, "learned"
    prov = provider or everyday()
    if want_cloud(question, force or provider is not None):
        reason = why_not(prov)
        if reason is None:
            try:
                text = ask_provider(prov, question, on_text)
                if text:
                    learned.save(question, text)
                    return text, prov
            except Exception as e:                                  # most specific first (see the SDK error docs)
                msg = _notice_for(prov, e)
                if msg:
                    return msg, "notice"
                # rate limit, overloaded, offline, timeout...: quietly fall back to the small brain
        elif force or provider is not None:
            return reason, "notice"
    import brain
    return brain.ask(question, on_text, examples=learned.similar(question)), "local"
