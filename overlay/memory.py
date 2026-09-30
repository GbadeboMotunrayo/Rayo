"""Rayo's memory: plain Markdown in an Obsidian vault you can read and edit.

    <vault>/Home.md               what this vault is
    <vault>/Memory/Facts.md       "Rayo, remember that …": one bullet per fact
    <vault>/Daily/YYYY-MM-DD.md   what you asked and what Rayo answered, per day

Default vault: ~/Documents/Rayo. Change it with {"memory": {"vault": "..."}}
in ~/.config/rayo/config.json; turn the daily log off with {"memory": {"log": false}}.
Open it in Obsidian and whatever you edit or delete there is what Rayo knows.
"""
import os, re, time, urllib.parse

import config

HOME_NOTE = """---
tags: [rayo]
---
# Rayo's memory

This vault is Rayo's memory. Everything in it is plain Markdown, so edit or
delete anything and Rayo will know (or forget) it next time.

- [[Facts]]: things you asked Rayo to remember. Say *"Rayo, remember that …"*.
  Rayo reads these before answering a question.
- **Daily/**: one note per day, logging what you asked and what Rayo said.

Voice commands: *"remember that …"*, *"what do you remember"*,
*"forget that"* (removes the last fact), *"open memory"*.
"""
FACTS_HEAD = """---
tags: [rayo, memory]
---
# Facts

Things Rayo remembers. "my" / "I" means you. One bullet per fact; the date links to that day's log.

"""
FACT_LINE = re.compile(r"^- (.+?)(?: \(\[\[(\d{4}-\d{2}-\d{2})\]\]\))?\s*$")


def vault():
    return os.path.expanduser(config.get("memory", "vault", "~/Documents/Rayo"))


def _path(*parts):
    return os.path.join(vault(), *parts)


def ensure():
    """Create the vault skeleton if it's missing (never overwrites your notes)."""
    for d in ("Memory", "Daily", ".obsidian"):
        os.makedirs(_path(d), exist_ok=True)
    for rel, body in (("Home.md", HOME_NOTE), ("Memory/Facts.md", FACTS_HEAD),
                      (".obsidian/daily-notes.json", '{"folder": "Daily", "format": "YYYY-MM-DD"}\n')):
        if not os.path.exists(_path(rel)):
            with open(_path(rel), "w") as f:
                f.write(body)


def _read_facts():
    try:
        with open(_path("Memory", "Facts.md")) as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    return [(m.group(1).strip(), m.group(2)) for m in map(FACT_LINE.match, lines) if m]


def facts():
    """Every fact, oldest first."""
    return [text for text, _ in _read_facts()]


def remember(fact):
    fact = re.sub(r"\s+", " ", fact).strip(" .")
    if not fact:
        return "remember what?"
    ensure()
    if fact.lower() in (f.lower() for f in facts()):
        return "I already know that"
    with open(_path("Memory", "Facts.md"), "a") as f:
        f.write(f"- {fact} ([[{time.strftime('%Y-%m-%d')}]])\n")
    return "got it, I'll remember that"


def forget_last():
    path = _path("Memory", "Facts.md")
    try:
        with open(path) as f:
            lines = f.read().splitlines(keepends=True)
    except OSError:
        return "I don't remember anything yet"
    for i in range(len(lines) - 1, -1, -1):
        if FACT_LINE.match(lines[i].rstrip("\n")):
            gone = FACT_LINE.match(lines[i].rstrip("\n")).group(1)
            del lines[i]
            with open(path, "w") as f:
                f.writelines(lines)
            return f"forgotten: {gone}"
    return "I don't remember anything yet"


def recall():
    items = facts()
    if not items:
        return "nothing yet. say “remember that …” and I will"
    last = items[-5:]
    more = f" (and {len(items) - 5} more in the vault)" if len(items) > 5 else ""
    return "I remember: " + "; ".join(last) + more


def relevant(question, budget=900):
    """Facts for the brain's prompt: ones sharing words with the question first, then the newest."""
    items = facts()
    words = {w for w in re.findall(r"[a-z]{3,}", question.lower())} - {"what", "the", "who", "how", "you", "and", "is"}
    scored = sorted(range(len(items)), key=lambda i: (-len(words & set(re.findall(r"[a-z]{3,}", items[i].lower()))), -i))
    out, used = [], 0
    for i in scored:
        if used + len(items[i]) > budget:
            break
        out.append(items[i]); used += len(items[i])
    return out


def log(heard, reply):
    """Append one exchange to today's daily note."""
    if not config.get("memory", "log", True) or not heard:
        return
    ensure()
    path = _path("Daily", time.strftime("%Y-%m-%d") + ".md")
    new = not os.path.exists(path)
    with open(path, "a") as f:
        if new:
            f.write(f"---\ntags: [rayo, daily]\n---\n# {time.strftime('%A %d %B %Y')}\n\n")
        f.write(f"- {time.strftime('%H:%M')} **you:** {heard}\n  **rayo:** {reply}\n")


def open_uri():
    """obsidian:// link that opens the vault (the app registers the scheme)."""
    return "obsidian://open?path=" + urllib.parse.quote(vault())
