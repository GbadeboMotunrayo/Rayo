"""The brain's hands: a short, fixed list of safe actions the LLM may request.

Design rules (see the agent-harness-construction skill):
  - few tools, stable names, narrow string inputs, one job each
  - every tool runs through commands.py, the same code as a spoken command
  - the model can only pick from TOOLS; anything else is refused
  - there is NO tool for power, deleting, sending, shell or settings, by design.
    A confused 1.7B model must never be able to turn off or damage anything.
"""
import re

import commands

MAX_CALLS = 3                     # one utterance can trigger at most three actions
MAX_ARG = 200

TOOLS = [
    {"name": "open", "description": "Open an app, folder, document, file or website by name. Examples: 'claude', 'downloads', 'youtube', 'the readme document'.",
     "params": {"target": "what to open"}},
    {"name": "search_web", "description": "Search the web in the browser.",
     "params": {"query": "what to search for"}},
    {"name": "weather", "description": "Spoken weather and rain forecast.",
     "params": {"when": "now, today, tonight or tomorrow"}},
    {"name": "remember", "description": "Save a fact the user wants remembered.",
     "params": {"fact": "the fact, in the user's words"}},
    {"name": "recall", "description": "Read back what has been remembered.", "params": {}},
    {"name": "battery", "description": "Laptop battery level and time left.", "params": {}},
    {"name": "volume", "description": "Change the sound volume.",
     "params": {"action": "up, down, mute or unmute"}},
    {"name": "media", "description": "Control playing music or video.",
     "params": {"action": "play_pause, next or previous"}},
    {"name": "status", "description": "A short system report: battery, temperature, memory and weather.", "params": {}},
]
NAMES = {t["name"] for t in TOOLS}


def schema():
    """Ollama/OpenAI-style tool definitions."""
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in t["params"].items()},
                       "required": list(t["params"])}}} for t in TOOLS]


FORBIDDEN = re.compile(r"\b(shut ?down|power ?off|reboot|restart|suspend|log ?out|sudo|rm|delete|erase|format|wipe|"
                       r"uninstall|passwords?|send)\b", re.I)


def _arg(args, key):
    v = args.get(key) if isinstance(args, dict) else None
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):      # no lists, dicts or nulls
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()[:MAX_ARG]


def to_plan(name, args):
    """One tool call → a commands.py plan. Raises ValueError for anything not allowed."""
    if name not in NAMES:
        raise ValueError(f"no tool called {name}")
    if name == "open":
        target = commands.clean(_arg(args, "target"))
        if not target:
            raise ValueError("open what?")
        if FORBIDDEN.search(target):                 # the hands never touch power, deleting or sending
            raise ValueError("that needs your confirmation. just say it to me directly, like: shut down")
        target = re.sub(r"^(?:the |my )?(.+?) (?:document|file)$", r"document \1", target)    # "readme document" → "document readme"
        target = re.sub(r"^(?:the |my )?(.+?) folder$", r"\1 folder", target)
        return commands._open_target(target)
    if name == "search_web":
        q = _arg(args, "query")
        if not q:
            raise ValueError("search for what?")
        return commands.resolve("search for " + q)
    if name == "weather":
        when = _arg(args, "when").lower()
        return commands.plan("weather", when if when in ("now", "today", "tonight", "tomorrow") else "now", "checking the weather")
    if name == "remember":
        fact = _arg(args, "fact")
        if not fact:
            raise ValueError("remember what?")
        return commands.plan("remember", fact, "")
    if name == "recall":
        return commands.plan("recall")
    if name == "battery":
        return commands.plan("battery")
    if name == "status":
        return commands.plan("status")
    if name == "volume":
        a = _arg(args, "action").lower()
        ops = {"up": ("+", "volume up"), "down": ("-", "volume down"), "mute": ("mute", "muted"), "unmute": ("unmute", "unmuted")}
        if a not in ops:
            raise ValueError("volume up, down, mute or unmute")
        return commands.plan("volume", *ops[a])
    if name == "media":
        a = _arg(args, "action").lower().replace(" ", "_")
        ops = {"play_pause": ("PlayPause", "play / pause"), "play": ("PlayPause", "play / pause"), "pause": ("PlayPause", "play / pause"),
               "next": ("Next", "next track"), "previous": ("Previous", "previous track")}
        if a not in ops:
            raise ValueError("play_pause, next or previous")
        return commands.plan("media", *ops[a])
    raise ValueError(name)


def run(calls):
    """Run the model's tool calls in order. Returns (spoken summary, hud_commands)."""
    done, huds, seen = [], [], set()
    for c in calls[:MAX_CALLS]:
        fn = c.get("function", c)
        name, args = fn.get("name", ""), fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                import json
                args = json.loads(args)
            except ValueError:
                args = {}
        key = (name, repr(sorted(args.items())) if isinstance(args, dict) else repr(args))
        if key in seen:                              # the model repeated itself
            continue
        seen.add(key)
        try:
            p = to_plan(name, args)
            if p["kind"] in ("ask", "none", "refuse", "brain"):      # nothing safe to do with it
                done.append(p["msg"] if p["kind"] != "brain" else "I didn't understand that")
                continue
            msg, hud = commands.execute(p)
            done.append(msg)
            if hud:
                huds.append(hud)
        except ValueError as e:
            done.append(f"I can't do that ({e})" if name in NAMES else "I can't do that")
    return "; ".join(d for d in done if d), huds
