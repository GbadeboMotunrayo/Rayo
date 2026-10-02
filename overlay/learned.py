"""What Rayo has learned from Claude: answers saved in your Obsidian vault.

Every answer Claude gives is saved to <vault>/Learned.md as plain Markdown. Next time you ask the
same thing she answers instantly, offline and free. When she has to fall back to the small local
model, the closest saved answers go into its prompt as examples, so it copies Claude's style and
facts. This is how the 1.7B "learns" without changing its weights.

You own it: open Learned.md in Obsidian and fix or delete any line.

Not saved: anything time-sensitive (news, weather, prices, "who is the current ..."), and
pronoun-dependent follow-ups ("and how old is he?") that mean nothing out of context.
"""
import os, re, time

STOP = {"the", "and", "for", "are", "was", "were", "you", "your", "what", "who", "how", "why", "when", "where", "which",
        "does", "did", "can", "could", "would", "should", "will", "tell", "about", "please", "with", "that", "this",
        "have", "has", "from", "into", "any", "some", "its", "than", "then", "there", "their", "them"}
VOLATILE = re.compile(r"\b(today|tonight|tomorrow|yesterday|now|current(ly)?|latest|news|weather|price|prices|score|scores|"
                      r"stock|exchange rate|this (week|month|year|morning|evening)|right now|recent(ly)?|trending|"
                      r"(president|ceo|prime minister|champion|winner) of)\b", re.I)
PRONOUN = re.compile(r"\b(he|she|it|they|him|her|them|that|this|those|these|his|hers|their|one)\b", re.I)
MAX_ENTRIES = 500
MAX_AGE_DAYS = 180
HEAD = """---
tags: [rayo, learned]
---
# Learned

Answers Rayo got from Claude and saved, so she can answer them instantly and offline next time.
Edit or delete any entry; she'll follow your version.

"""
ENTRY = re.compile(r"^- \*\*Q:\*\* (.+)\n  \*\*A:\*\* (.+?)(?: \(\[\[(\d{4}-\d{2}-\d{2})\]\]\))?$", re.M)


def _path():
    import memory
    return os.path.join(memory.vault(), "Learned.md")


def tokens(text):
    words = {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOP}
    nums = set(re.findall(r"\d+", text))
    return words, nums


def similarity(a, b):
    (wa, na), (wb, nb) = tokens(a), tokens(b)
    if na != nb or not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def entries():
    try:
        with open(_path()) as f:
            text = f.read()
    except OSError:
        return []
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - MAX_AGE_DAYS * 86400))
    return [(q.strip(), a.strip(), d or "") for q, a, d in ENTRY.findall(text) if not d or d >= cutoff]


def cacheable(question):
    q = question.strip()
    return not VOLATILE.search(q) and not (PRONOUN.search(q) and len(q.split()) <= 7) and len(tokens(q)[0]) >= 2


def lookup(question, threshold=0.75):
    """A saved answer for (nearly) this exact question, or None."""
    if not cacheable(question):
        return None
    best = max(((similarity(question, q), a) for q, a, _ in entries()), default=(0.0, None))
    return best[1] if best[0] >= threshold else None


def similar(question, n=3, floor=0.3):
    """The closest saved Q&As, as few-shot examples for the local model."""
    scored = sorted(((similarity(question, q), q, a) for q, a, _ in entries()), reverse=True)
    return [(q, a) for s, q, a in scored[:n] if s >= floor]


def save(question, answer):
    """Remember Claude's answer. Returns True if it was saved."""
    question, answer = " ".join(question.split()), " ".join(answer.split())
    if not cacheable(question) or not answer or lookup(question, 0.9):
        return False
    import memory
    memory.ensure()
    path = _path()
    kept = entries()[-(MAX_ENTRIES - 1):]
    new = not os.path.exists(path)
    lines = [f"- **Q:** {q}\n  **A:** {a}" + (f" ([[{d}]])" if d else "") for q, a, d in kept]
    lines.append(f"- **Q:** {question}\n  **A:** {answer} ([[{time.strftime('%Y-%m-%d')}]])")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(HEAD + "\n".join(lines) + "\n")
    os.replace(tmp, path)
    if new:                                          # link it from the vault's home note
        home = os.path.join(os.path.dirname(path), "Home.md")
        try:
            if "[[Learned]]" not in open(home).read():
                with open(home, "a") as f:
                    f.write("\n- [[Learned]]: answers Rayo got from Claude and saved, so she can answer them offline next time.\n")
        except OSError:
            pass
    return True
