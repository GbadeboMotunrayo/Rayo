"""Claude Code conversations as notes in your Obsidian vault.

Claude Code stores every chat as one big .jsonl file (mostly tool output) in ~/.claude/projects, which
Obsidian can't read. This turns each chat into a clean Markdown note:

    <vault>/Conversations/2026-10-02 Caveman skill installation (22d4ff01).md
    <vault>/Conversations/Index.md          newest first, with links

Only what you and Claude said is kept: your messages and Claude's replies. Tool calls, tool output, hidden
reasoning and system reminders are left out. Anything that looks like a secret (API keys, tokens, private
keys, passwords) is replaced by [REDACTED], because these chats contain things you pasted.

Run:  python3 overlay/chats.py            (or say "sync my chats" to Rayo)
      python3 overlay/chats.py --force    re-export everything
It is safe to run again and again: unchanged chats are skipped, and a chat that grows is updated in place.
Read-only on your Claude data; it only ever writes inside <vault>/Conversations.
"""
import os, re, sys, json, glob, time, datetime, argparse

PROJECTS = os.path.expanduser("~/.claude/projects")
FOLDER = "Conversations"

SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
]
ASSIGNED = re.compile(r"(?i)\b((?:api[_-]?key|secret|token|passw(?:or)?d|passwd|private[_-]?key)[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9_\-./+=]{16,})")
# blocks Claude Code injects into user turns that you never typed
INJECTED = re.compile(r"<(system-reminder|local-command-caveat|local-command-stdout|command-message|command-args|"
                      r"task-notification|ide_[a-z_]+)>[\s\S]*?</\1>", re.I)
UNWRAP = re.compile(r"</?(?:pasted_content|command-name|user-prompt-submit-hook)[^>]*>", re.I)


def redact(text):
    for rx in SECRETS:
        text = rx.sub("[REDACTED]", text)
    return ASSIGNED.sub(lambda m: m.group(1) + "[REDACTED]", text)


def clean_user(text):
    text = INJECTED.sub("", text)
    text = UNWRAP.sub("", text)
    return text.strip()


def _text_of(content, user):
    """Plain text from a message's content (a string or a list of blocks)."""
    if isinstance(content, str):
        return clean_user(content) if user else content.strip()
    parts = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            parts.append(clean_user(b.get("text", "")) if user else b.get("text", "").strip())
        elif b.get("type") == "image" and user:
            parts.append("*[image]*")
    return "\n\n".join(p for p in parts if p)


def _local_time(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return None


def parse(path):
    """One .jsonl chat -> {"id","title","started","cwd","turns":[(who, datetime, text, tools)]}."""
    sid = os.path.splitext(os.path.basename(path))[0]
    title, cwd, turns = None, None, []
    with open(path, errors="replace") as f:
        for line in f:
            if '"custom-title"' not in line and '"type":"user"' not in line and '"type":"assistant"' not in line \
                    and '"type": "user"' not in line and '"type": "assistant"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            kind = o.get("type")
            if kind == "custom-title" and o.get("customTitle"):
                title = o["customTitle"]
                continue
            if o.get("isSidechain") or kind not in ("user", "assistant"):
                continue
            cwd = cwd or o.get("cwd")
            msg = o.get("message") or {}
            when = _local_time(o.get("timestamp"))
            if kind == "user":
                text = _text_of(msg.get("content"), True)
                if text:
                    turns.append(["you", when, text, 0])
            else:
                blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
                text = _text_of(blocks, False)
                tools = sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use")
                if turns and turns[-1][0] == "claude":           # one reply is many small records: join them
                    turns[-1][2] = (turns[-1][2] + "\n\n" + text).strip() if text else turns[-1][2]
                    turns[-1][3] += tools
                elif text or tools:
                    turns.append(["claude", when, text, tools])
    first_you = next((t[2] for t in turns if t[0] == "you"), "")
    title = title or " ".join(first_you.split())[:60] or "Untitled chat"
    started = next((t[1] for t in turns if t[1]), None)
    return {"id": sid, "title": title, "started": started, "cwd": cwd, "turns": [tuple(t) for t in turns]}


def _safe(name, limit=70):
    name = re.sub(r'[\\/:*?"<>|#^\[\]\n\r\t]+', " ", name)
    return re.sub(r"\s+", " ", name).strip(" .")[:limit] or "Untitled"


def render(chat):
    started = chat["started"]
    home = os.path.expanduser("~")
    project = (chat["cwd"] or "").replace(home, "~") or "unknown"
    you = sum(1 for t in chat["turns"] if t[0] == "you")
    head = ["---", "tags: [claude-chat]", f"session: {chat['id']}", f"project: \"{project}\"",
            f"started: {started.strftime('%Y-%m-%d %H:%M') if started else 'unknown'}", f"messages: {you}", "---",
            f"# {chat['title']}", "", f"*{project} · {you} message{'s' if you != 1 else ''} from you*", ""]
    body, last_day = [], None
    for who, when, text, tools in chat["turns"]:
        day = when.strftime("%Y-%m-%d") if when else None
        if day and day != last_day:
            body += [f"## {day}", ""]
            last_day = day
        stamp = when.strftime("%H:%M") if when else ""
        if who == "you":
            body += [f"### 🧑 You · {stamp}", "", text, ""]
        else:
            note = f"\n\n*(used {tools} tool{'s' if tools != 1 else ''})*" if tools else ""
            body += [f"### 🤖 Claude · {stamp}", "", (text or "*(working…)*") + note, ""]
    return redact("\n".join(head + body))


def export_all(vault=None, projects=None, force=False, only=None):
    """Export every chat. Returns (written, skipped, total)."""
    if vault is None:
        import memory
        vault = memory.vault()
    out = os.path.join(vault, FOLDER)
    os.makedirs(out, mode=0o700, exist_ok=True)
    state_path = os.path.join(out, ".export-state.json")
    try:
        state = json.load(open(state_path))
    except (OSError, ValueError):
        state = {}
    files = sorted(glob.glob(os.path.join(projects or PROJECTS, "*", "*.jsonl")))
    if only:
        files = [p for p in files if only in p]
    written = skipped = 0
    index = []
    for path in files:
        st = os.stat(path)
        sid = os.path.splitext(os.path.basename(path))[0]
        sig = [int(st.st_mtime), st.st_size]
        prev = state.get(sid)
        if not force and prev and prev.get("sig") == sig and os.path.exists(os.path.join(out, prev.get("file", "?"))):
            skipped += 1
            index.append(prev["index"])
            continue
        chat = parse(path)
        if not any(t[0] == "you" for t in chat["turns"]):
            continue                                     # nothing you said: not worth a note
        day = chat["started"].strftime("%Y-%m-%d") if chat["started"] else "undated"
        name = f"{day} {_safe(chat['title'])} ({sid[:8]}).md"
        if prev and prev.get("file") and prev["file"] != name:
            try:
                os.remove(os.path.join(out, prev["file"]))   # the chat was renamed: replace its old note
            except OSError:
                pass
        target = os.path.join(out, name)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(render(chat))
        you = sum(1 for t in chat["turns"] if t[0] == "you")
        entry = {"day": day, "title": chat["title"], "file": name, "you": you,
                 "project": (chat["cwd"] or "").replace(os.path.expanduser("~"), "~")}
        state[sid] = {"sig": sig, "file": name, "index": entry}
        index.append(entry)
        written += 1
    _write_index(out, index)
    json.dump(state, open(state_path, "w"))
    _link_from_home(vault)
    return written, skipped, written + skipped


def _write_index(out, entries):
    lines = ["---", "tags: [claude-chat, index]", "---", "# Conversations", "",
             "Your chats with Claude, exported from Claude Code. Secrets are redacted. "
             "Say *\"Rayo, sync my chats\"* to refresh.", ""]
    for e in sorted(entries, key=lambda e: e["day"], reverse=True):
        lines.append(f"- {e['day']} [[{e['file'][:-3]}|{e['title']}]] · {e['you']} message{'' if e['you'] == 1 else 's'} · `{e['project']}`")
    tmp = os.path.join(out, "Index.md.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, os.path.join(out, "Index.md"))


def _link_from_home(vault):
    home = os.path.join(vault, "Home.md")
    try:
        text = open(home).read()
        if "Conversations/Index" not in text:
            with open(home, "a") as f:
                f.write("\n- [[Conversations/Index|Conversations]]: your chats with Claude, exported as notes (secrets redacted).\n")
    except OSError:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Export Claude Code chats to your Obsidian vault.")
    ap.add_argument("--vault", help="vault folder (default: your Rayo vault)")
    ap.add_argument("--projects", help="Claude projects folder (default: ~/.claude/projects)")
    ap.add_argument("--only", help="only chats whose path contains this text, e.g. herohud")
    ap.add_argument("--force", action="store_true", help="re-export everything")
    a = ap.parse_args()
    if a.vault is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    t0 = time.time()
    w, s, total = export_all(a.vault, a.projects, a.force, a.only)
    print(f"{total} conversation(s): {w} written, {s} unchanged  ({time.time() - t0:.1f}s)")
