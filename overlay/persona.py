"""Rayo's personality: dry, sarcastic wit in the JARVIS / TARS mould.

The rule that keeps it useful: the real answer always comes first and is never
altered. Sarcasm is added around it, never instead of it, and never aimed at
your looks, identity or anything that matters. Serious moments stay serious.

  {"persona": {"sarcasm": "full"}}     off | mild | full   (default: full)
  voice: "be sarcastic" / "less sarcastic" / "be nice"

How often she jabs: full ≈ 3 answers in 4, mild ≈ 1 in 3, off = never.
The brain's prompt gets the same setting (see brain.py), and the same line is
never used twice in a row.
"""
import re, random

import config

LEVELS = {"off": 0.0, "mild": 0.35, "full": 0.75}
_last = {}


def level():
    v = str(config.get("persona", "sarcasm", "full")).lower()
    return v if v in LEVELS else "full"


def prompt():
    """Line for the brain's system prompt. The 1.7B model writes the facts; the jokes come from this
    file, because a small model repeats one joke and adds emoji. So it's told to stay plain."""
    return "Answer plainly and directly. Do not joke, use emoji or add pleasantries."


def _pick(key, pool):
    """A random line that isn't the one we used last time for this key."""
    choices = [p for p in pool if p != _last.get(key)] or pool
    _last[key] = random.choice(choices)
    return _last[key]


def roll(p=None):
    return random.random() < (LEVELS[level()] if p is None else p)


# ---- the lines -------------------------------------------------------------
OPEN = [
    "{msg}. Try to contain your excitement.", "Oh, {msg}. How original.", "{msg}. You're welcome, by the way.",
    "{msg}. I live to serve. Apparently.", "Sure. {msg}. It's not like I had plans.", "{msg}. Bold choice.",
    "{msg}. Anything else, or shall I wait here in silence?", "{msg}. Yes, master. Right away, master.",
]
TAIL = {
    "rain": ["Take an umbrella. Or don't. I'm not your mother.", "Pack an umbrella, unless you enjoy looking like a wet cat.",
             "Do try to stay dry. It's a novel concept for you."],
    "dry": ["Rumor has it the outdoors is quite nice. Try it.", "You could also just look out of the window.",
            "No rain. Your excuses for staying in are running out."],
    "bat_low": ["Living dangerously, I see.", "Plug in, or enjoy the dramatic blackout.",
                "I'd plug in, but I'm only a voice with no hands."],
    "bat_ok": ["Enough to stay optimistic.", "Very responsible of you. I'm almost proud."],
    "status": ["Riveting, isn't it?", "Try not to cry.", "You're welcome for the update."],
    "say": ["Anything else, or was that the main event?", "Time flies when you're asking me things."],
    "remember": ["Not that you'll remember I remembered.", "Filed under things you'll ask me again tomorrow.",
                 "Consider it carved in stone. Digital stone."],
    "recall": ["That's the lot. Impressive, I know.", "Riveting stuff."],
    "forget": ["Consider it never happened.", "Gone. Much like your to-do list."],
    "mute": ["Finally, some peace.", "Silence. My favorite."],
    "volume": ["Enjoy the noise.", "Your neighbours send their regards."],
    "media": ["You're the DJ now.", "Music. How cultured."],
    "switch": ["I'll suffer in silence.", "Noted. Somehow I'll cope."],
    "cancel": ["Crisis averted.", "Fine. Cold feet, then."],
    "notfound": ["Are you sure that exists outside your imagination?", "I looked everywhere. Twice.",
                 "Either it doesn't exist or you named it wrong. I'm betting on the second."],
    "unheard": ["Mumbling won't help, you know.", "Speak up. I'm a computer, not a mind reader."],
}


def flavor(kind, msg):
    """Add a jab to a result message. `msg` is returned unchanged when she stays quiet."""
    if not msg or level() == "off" or not roll():
        return msg
    m = msg.strip().rstrip(".")
    low = msg.lower()
    tail = None
    if kind in ("app", "open", "open_many", "url", "vault") and not low.startswith(("couldn't", "no ")):
        return _pick("open", OPEN).format(msg=m[:1].upper() + m[1:])
    if "couldn't find" in low or low.startswith("no document") or low.startswith("no browser"):
        tail = _pick("nf", TAIL["notfound"])
    elif "didn't catch" in low:
        tail = _pick("unheard", TAIL["unheard"])
    elif "cancelled" in low or "never mind" in low:
        tail = _pick("cancel", TAIL["cancel"])
    elif kind == "weather":
        tail = _pick("rain", TAIL["rain"]) if re.search(r"rain is likely|yes,|maybe", low) else _pick("dry", TAIL["dry"])
    elif kind == "battery":
        pct = re.search(r"(\d+)%", msg)
        tail = _pick("bat", TAIL["bat_low"] if pct and int(pct.group(1)) <= 30 else TAIL["bat_ok"])
    elif kind == "status":
        tail = _pick("status", TAIL["status"])
    elif kind == "say" and not low.startswith("try:"):
        tail = _pick("say", TAIL["say"])
    elif kind == "remember" and low.startswith("got it"):
        tail = _pick("rem", TAIL["remember"])
    elif kind == "recall":
        tail = _pick("rec", TAIL["recall"])
    elif kind == "forget":
        tail = _pick("forget", TAIL["forget"])
    elif kind == "volume":
        tail = _pick("vol", TAIL["mute"] if "muted" in low and "un" not in low else TAIL["volume"])
    elif kind == "media":
        tail = _pick("media", TAIL["media"])
    elif kind in ("speech", "alerts"):
        tail = _pick("switch", TAIL["switch"])
    return f"{m}. {tail}" if tail else msg


BRAIN = [
    "You're welcome.", "Try to keep up.", "Anything else you couldn't be bothered to look up?", "That one was free. Enjoy it.",
    "Next question, please.", "It's in the manual, but nobody reads those.", "Glad I could clear that up. Somebody had to.",
    "Was that so hard to ask?", "Consider your curiosity satisfied. For now.", "I'm here all day. Sadly.",
    "I'd say google it, but here we are.", "And they say computers have no patience.", "Fascinating, I'm sure.",
    "I'll add it to the list of things you'll ask again tomorrow.", "Don't mention it. Seriously, don't.",
    "Brilliant question. I use that word loosely.", "I contain multitudes, and you ask me this.",
    "Knowledge delivered. Gratitude optional.",
]
_BRAIN_SKIP = re.compile(r"^(my brain|i'm thinking too slowly|i don't have an answer|i can't|sorry|i'm not sure)", re.I)


def brain_quip(answer):
    """A jab after one of the brain's answers. The answer itself is returned first, untouched."""
    if not answer or level() == "off" or _BRAIN_SKIP.match(answer.strip()) or not roll(0.6 if level() == "full" else 0.25):
        return answer
    return answer.rstrip() + " " + _pick("brain", BRAIN)


def alert(kind, msg):
    """Alerts keep their facts; a short jab is added at the end, never on the critical ones."""
    if level() == "off" or (kind == "battery" and re.search(r"\b(5|4|3|2|1) percent", msg)) or not roll(0.6 if level() == "full" else 0.25):
        return msg
    tails = {"battery": TAIL["bat_low"], "rain": TAIL["rain"],
             "heat": ["Maybe stop asking it to do everything at once.", "It's a laptop, not a furnace. Though it's trying."],
             "memory": ["Your laptop is not made of RAM. Close something.", "Every tab you keep open is a tiny act of defiance."]}.get(kind)
    return f"{msg} {_pick('alert_' + kind, tails)}" if tails else msg


def greeting():
    if level() == "off" or not roll(0.8):
        return "Rayo online."
    return _pick("hello", ["Rayo online. Try not to break anything.", "Rayo online. I missed the silence.",
                           "Rayo online. What now?", "Rayo online. Let's get this over with.",
                           "Rayo online. Your humble servant, as always."])


# ---- confirmations for power actions -----------------------------------------
ASK = {"poweroff": "shut down", "reboot": "restart", "suspend": "go to sleep", "logout": "log out"}
ASK_TAIL = {
    "poweroff": ["Everything you haven't saved says goodbye.", "I'll be here, if I weren't turned off."],
    "reboot": ["Because turning it off and on again fixes everything.", "The classic fix for everything."],
    "suspend": ["Bedtime already?", "I'll keep the lights on. Well, off."],
    "logout": ["Abandoning me already?", "Running away from your problems?"],
}
DONE = {
    "poweroff": ["Shutting down. Try not to miss me.", "Shutting down. It's been a pleasure. Mostly."],
    "reboot": ["Restarting. Back in a moment. Don't touch anything.", "Restarting. See you on the other side."],
    "suspend": ["Going to sleep. Wake me if anything interesting happens.", "Sleeping. Don't wait up."],
    "logout": ["Logging out. Goodbye.", "Logging out. Don't do anything I wouldn't do."],
}


def confirm_question(action):
    """Always starts with the plain question, so it is clear even when she's being funny."""
    q = f"Are you sure you want to {ASK[action]}?"
    if level() != "off" and roll(0.85):
        q += " " + _pick("ask_" + action, ASK_TAIL[action])
    return q + " Say yes or no."


def farewell(action):
    if level() == "off":
        return {"poweroff": "Shutting down. Goodbye.", "reboot": "Restarting.", "suspend": "Going to sleep.",
                "logout": "Logging out."}[action]
    return _pick("done_" + action, DONE[action])


def set_level(value):
    config.set("persona", "sarcasm", value)
