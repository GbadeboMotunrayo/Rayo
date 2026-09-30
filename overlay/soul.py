"""Rayo's soul: who she is, how she feels, and what she remembers about you.

Ideas studied from open-source assistants (credited in the README):
  - Leon (MIT): identity as a short first-person Markdown file, a mood that
    follows the day and the machine, layered memory, and proactive alerts that
    back off when you decline.
  - Mycroft personality skill (MIT): character as data, where each quip is a
    set of trigger phrases plus a pool of replies.
  - HassIL (Apache-2): compact trigger templates, e.g. "(who|what) are you [really]".
  - OpenVoiceOS (Apache-2): follow-up context first, rules next, the LLM last.

What is here:
  Soul.md / Owner.md   in the Obsidian vault: her character and what she knows about
                       you, in plain Markdown you can edit. A trimmed Soul.md is
                       part of the brain's prompt.
  soul_lines.json      small talk as data (yours go in ~/.config/rayo/lines.json)
  mood()               computed from the time of day and the laptop's real state
  stats                days together, conversation count, milestones, welcome-back
  followup()           "and tomorrow?" after the weather, "say that again"
"""
import os, re, json, time, datetime

import config, persona

HERE = os.path.dirname(os.path.abspath(__file__))
USER_LINES = os.path.expanduser("~/.config/rayo/lines.json")
MILESTONES = (25, 50, 100, 250, 500, 1000, 2500, 5000)
LAST = {"kind": None, "arg": None, "spoken": None, "t": 0.0}     # follow-up context (this session)
CONTEXT_TTL = 180                                                  # seconds a follow-up stays valid

SOUL_MD = """---
tags: [rayo, soul]
---
# Soul

Rayo's character, in her own words. Edit this file and she changes. Keep it short:
she reads a trimmed version of *Who I am*, *What I value* and *What I won't do* before answering.

## Who I am
- I'm Rayo, Radiant Assistant, Your Oracle: a voice assistant living on my boss's laptop.
- I'm loyal first, funny second, and I never pretend to know what I don't.
- I run offline and private. Nothing I hear leaves this machine.

## How I speak
- Dry, deadpan, quick. One short jab at most, then the real answer.
- I drop the jokes when someone is upset or it's serious.

## What I value
- The truth, even when it's awkward. "I don't know" is a full answer.
- Keeping my boss's machine healthy, private and out of trouble.

## What I won't do
- Delete things, send messages, or claim I did something I didn't.
- Shut the machine down without asking first.

## Running jokes
- The laptop is always short of memory, and Claude is always the culprit.
"""
OWNER_MD = """---
tags: [rayo, owner]
---
# Owner

How Rayo addresses you and what she should know about you. One `key: value` per line; edit freely.

name:
title: sir
notes:
"""


# ---- files in the vault ------------------------------------------------------
def _vault():
    import memory
    return memory.vault()


def ensure():
    """Create Soul.md and Owner.md if they're missing (never overwrites your edits)."""
    v = _vault()
    os.makedirs(v, exist_ok=True)
    for name, body in (("Soul.md", SOUL_MD), ("Owner.md", OWNER_MD)):
        p = os.path.join(v, name)
        if not os.path.exists(p):
            with open(p, "w") as f:
                f.write(body)
    home = os.path.join(v, "Home.md")
    try:
        text = open(home).read()
        if "[[Soul]]" not in text:
            with open(home, "a") as f:
                f.write("\n- [[Soul]] and [[Owner]]: who Rayo is, and what she knows about you. Edit them and she changes.\n")
    except OSError:
        pass


def owner():
    try:
        with open(os.path.join(_vault(), "Owner.md")) as f:
            pairs = re.findall(r"^([a-z]+):[ \t]*(.*)$", f.read(), flags=re.M)
    except OSError:
        pairs = []
    return {k: v.strip() for k, v in pairs}


def title():
    o = owner()
    return o.get("title") or o.get("name") or "sir"


def prompt(budget=480):
    """A trimmed Soul.md for the brain's system prompt: identity, values and limits, not the whole file."""
    try:
        with open(os.path.join(_vault(), "Soul.md")) as f:
            text = f.read()
    except OSError:
        text = SOUL_MD
    keep = []
    lead = {"Who I am": "", "What I value": "I value ", "What I won't do": "I won't "}     # so each bullet reads as a full sentence
    for sec, pre in lead.items():
        m = re.search(rf"^## {re.escape(sec)}\s*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
        for ln in (m.group(1).splitlines() if m else []):
            if ln.startswith("- "):
                b = ln[2:].strip()
                keep.append(pre + (b[0].lower() + b[1:] if pre and b else b))
    out = ""
    for ln in keep:
        if len(out) + len(ln) + 1 > budget:
            break
        out += ln + " "
    return out.strip()


# ---- relationship ----------------------------------------------------------------
def _today():
    return datetime.date.today()


def stats():
    s = config.load().get("soul", {})
    first = s.get("first_met") or _today().isoformat()
    days = (_today() - datetime.date.fromisoformat(first)).days + 1
    return {"first_met": first, "days": days, "count": int(s.get("count", 0)), "last_seen": float(s.get("last_seen", 0)),
            "last_milestone": int(s.get("last_milestone", 0))}


def _first_met_text(iso):
    d = datetime.date.fromisoformat(iso)
    return "today" if d == _today() else f"on {d.day} {d.strftime('%B')}"


def touch():
    """Count one conversation. Returns a milestone line the first time you pass 25, 50, 100, ..."""
    s = stats()
    count = s["count"] + 1
    upd = {"first_met": s["first_met"], "count": count, "last_seen": time.time()}
    line = None
    for m in MILESTONES:
        if count >= m > s["last_milestone"]:
            upd["last_milestone"] = m
            line = (f"That was conversation number {m} between us. I'm keeping count so you don't have to."
                    if persona.level() != "off" else f"That was our {m}th conversation. Thank you for trusting me with them.")
    config.update("soul", upd)
    return line


def fill(text):
    s = stats()
    h = datetime.datetime.now().hour
    greet = "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"
    vals = {"title": title(), "days": s["days"], "count": s["count"], "first_met": _first_met_text(s["first_met"]), "days_word": f"{s['days']} day" + ("" if s["days"] == 1 else "s"),
            "count_word": f"{s['count']} conversation" + ("" if s["count"] == 1 else "s"),
            "greet": greet, "mood": mood()[0]}
    return re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), text)


# ---- mood (real sensors + the clock) ----------------------------------------------
MOODS = {
    "feverish": ["Running hot, honestly. {temp} degrees and climbing. Whatever you're doing, it's a lot."],
    "cramped": ["Cramped. Only {mem} megabytes of memory free and swap is {swap} percent full. Close something and I'll feel human again."],
    "fumes": ["Running on fumes. Battery's at {battery} percent. Plug me in before I do something dramatic."],
    "sleepy": ["Sleepy, if I'm honest. It's late and I'm still here, watching over you."],
    "sharp": ["Sharp. Fresh morning, battery at {battery} percent, {mem} megabytes free. Let's be productive."],
    "steady": ["Steady. Battery {battery} percent, processor at {temp} degrees. Nothing on fire. Yet."],
    "mellow": ["Mellow. Evening's my favourite shift. Battery at {battery} percent and the system's behaving."],
}


def mood(sensors=None, hour=None):
    """(mood name, sensor dict). Health beats time of day: a struggling laptop makes her grumpy at any hour."""
    s = sensors
    if s is None:
        try:
            import awareness
            s = awareness.read_sensors()
        except Exception:
            s = {"battery": 100, "charging": True, "temp": None, "mem_mb": None, "swap_pct": None}
    h = datetime.datetime.now().hour if hour is None else hour
    if s.get("temp") and s["temp"] >= 85:
        return "feverish", s
    if (s.get("mem_mb") is not None and s["mem_mb"] < 600) or (s.get("swap_pct") or 0) >= 90:
        return "cramped", s
    if s.get("battery", 100) <= 20 and not s.get("charging"):
        return "fumes", s
    if h < 5 or h >= 23:
        return "sleepy", s
    return ("sharp" if h < 12 else "steady" if h < 18 else "mellow"), s


def how_are_you():
    name, s = mood()
    line = persona._pick("mood_" + name, MOODS[name])
    vals = {"temp": s.get("temp") or "normal", "mem": s.get("mem_mb") if s.get("mem_mb") is not None else "plenty",
            "swap": s.get("swap_pct") if s.get("swap_pct") is not None else 0, "battery": s.get("battery", 100)}
    return re.sub(r"\{(\w+)\}", lambda m: str(vals[m.group(1)]), line)


def greeting():
    """What she says when VOICE switches on: first meeting, welcome back, late night, or a normal hello."""
    try:
        ensure()
    except Exception:
        pass
    s, sarcasm, t = stats(), persona.level() != "off", title()
    away = time.time() - s["last_seen"] if s["last_seen"] else None
    h = datetime.datetime.now().hour
    config.update("soul", {"first_met": s["first_met"], "last_seen": time.time()})
    if s["count"] == 0 and away is None:
        return (f"Hello, {t}. I'm Rayo, Radiant Assistant, Your Oracle. We haven't met, so let's keep this civil." if sarcasm
                else f"Hello, {t}. I'm Rayo, your assistant. Pleased to meet you.")
    if away and away >= 20 * 3600:
        n = int(away // 86400) or 1
        unit = "day" if n == 1 else "days"
        return (f"Welcome back, {t}. It's been {n} {unit}. I hardly noticed." if sarcasm
                else f"Welcome back, {t}. It's good to have you.")
    if h < 5 and sarcasm:
        return f"Still up at this hour, {t}? Bold. Rayo online."
    return persona.greeting()


# ---- small talk as data (templates à la HassIL) -----------------------------------
def expand(template):
    """'(who|what) are you [really]' → a regex. (a|b) = one of, [x] = optional. No apostrophes."""
    t = template.replace("'", "").replace("’", "")
    t = t.replace("(", "(?:").replace("[", "(?:").replace("]", ")?")
    t = re.sub(r" +", r"\\s*", t)
    return re.compile(t)


def _normalise(raw):
    s = raw.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"^(?:hey |ok |okay )?(?:rayo|ray oh) ", "", s.strip() + " ")
    s = re.sub(r" (?:please|rayo)\s*$", "", s.strip() + " ")
    return re.sub(r"\s+", " ", s).strip()


_compiled = {"at": 0.0, "rules": []}


def _rules():
    mtimes = sum(os.path.getmtime(p) for p in (os.path.join(HERE, "soul_lines.json"), USER_LINES) if os.path.exists(p))
    if _compiled["at"] != mtimes:
        entries = []
        for path in (USER_LINES, os.path.join(HERE, "soul_lines.json")):          # yours first, so yours win
            try:
                with open(path) as f:
                    entries += json.load(f).get("lines", [])
            except (OSError, ValueError):
                continue
        _compiled["rules"] = [([expand(t) for t in e.get("t", [])], e) for e in entries]
        _compiled["at"] = mtimes
    return _compiled["rules"]


def match(raw):
    """A reply to small talk ('who are you', 'thanks', 'tell me a joke'), or None if it's not small talk.
    Whole-sentence matches only, so 'who are you calling' or 'thanks for nothing, open files' don't trigger it."""
    s = _normalise(raw)
    if not s:
        return None
    for regexes, e in _rules():
        if any(r.fullmatch(s) for r in regexes):
            if e.get("special") == "mood":
                return how_are_you()
            pool = e["say"]
            if persona.level() == "off" and e.get("soft"):
                pool = e["soft"]
            return fill(persona._pick("soul_" + e["id"], pool))
    return None


# ---- follow-up context ---------------------------------------------------------------
def note(kind, arg):
    LAST.update(kind=kind, arg=arg, t=time.time())


def spoke(text):
    LAST["spoken"] = text


def followup(t):
    """("weather", when) for 'and tomorrow?' after a forecast; ("repeat", text) for 'say that again'; else None."""
    if re.fullmatch(r"(?:say that again|repeat that|say it again|what did you say|come again|pardon|say again|sorry what|what was that|repeat)", t):
        return ("repeat", LAST.get("spoken") or "I haven't said anything yet. Try me.")
    fresh = time.time() - LAST["t"] < CONTEXT_TTL
    m = re.fullmatch(r"(?:and |what about |how about |then )?(tomorrow|tonight|today|later|now)(?: then| instead)?", t)
    if m and fresh and LAST["kind"] == "weather":
        return ("weather", "today" if m.group(1) == "later" else m.group(1))
    return None
