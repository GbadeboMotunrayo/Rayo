"""Rayo's awareness: she speaks up first when something needs your attention.

Runs inside the voice process, so it is only active while VOICE is on (on =
Rayo is alive, off = silent). Checked every CHECK_EVERY seconds between
commands, never while you are talking to her. Each alert has its own cooldown,
so she never nags:

  battery   20% / 10% / 5% while unplugged; "fully charged" at 100% while plugged in
  heat      CPU hot for two checks in a row, naming the process eating it
  memory    under ~450MB free or swap almost full, naming the biggest process
  rain      70%+ chance in the next few hours (once per rain window)

Settings (~/.config/rayo/config.json), all optional:
  {"awareness": {"on": true, "quiet": ["23:00", "07:00"], "speak": true}}
Quiet hours still show the alert on the HUD; they just don't speak it.
Voice: "stop alerts" / "alerts on" / "status report".
"""
import os, re, time, subprocess, threading

import config

CHECK_EVERY = 30                 # seconds between checks
COOLDOWN = {"battery": 0, "heat": 1200, "memory": 1800, "rain": 4 * 3600, "charged": 6 * 3600}
BATTERY_STEPS = (20, 10, 5)
HOT_C = 88
LOW_MEM_MB = 450
_state = {"last": {}, "bat_said": set(), "hot_run": 0, "rain_fetch": 0.0, "rain_msg": None}


def enabled():
    return bool(config.get("awareness", "on", True))


def snoozed():
    return time.time() < float(config.get("awareness", "snooze_until", 0))


def quiet_now():
    q = config.get("awareness", "quiet", ["23:00", "07:00"])
    try:
        a, b = (tuple(int(x) for x in s.split(":")) for s in q)
    except (ValueError, TypeError):
        return False
    now = time.localtime()
    cur = (now.tm_hour, now.tm_min)
    return (a <= cur < b) if a <= b else (cur >= a or cur < b)


# ---- sensors ---------------------------------------------------------------
def top_process(by="cpu"):
    """(name, cpu %, rss MB) of the heaviest process that isn't Rayo or the kernel."""
    out = subprocess.run(["ps", "-eo", "pcpu,rss,comm", "--sort=-" + ("pcpu" if by == "cpu" else "rss")],
                         capture_output=True, text=True).stdout.splitlines()[1:]
    for line in out:
        cpu, rss, comm = line.split(None, 2)
        if comm.startswith(("ps", "python", "kworker", "ksoftirqd", "pw-")):
            continue
        return friendly(comm), float(cpu), int(rss) // 1024
    return None


NICE = {"llama-server": "the AI model server", "claude-desktop": "Claude", "claude": "Claude", "firefox": "Firefox",
        "brave": "Brave", "chromium": "Chromium", "WebKitWebProces": "a web view", "Isolated Web Co": "a Firefox tab",
        "Web Content": "a browser tab", "gnome-shell": "the desktop", "obsidian": "Obsidian", "node": "Node", "npm": "npm"}


def friendly(comm):
    return NICE.get(comm, comm)


def read_sensors():
    import stats
    pct, charging, status, mins = stats.battery_info()
    avail_mb = swap_used_pct = None
    mem = {}
    for line in open("/proc/meminfo"):
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0])
    avail_mb = mem.get("MemAvailable", 0) // 1024
    if mem.get("SwapTotal"):
        swap_used_pct = 100 * (mem["SwapTotal"] - mem["SwapFree"]) // mem["SwapTotal"]
    return {"battery": pct, "charging": charging, "mins": mins, "temp": stats.cpu_temp(),
            "mem_mb": avail_mb, "swap_pct": swap_used_pct}


# ---- the checks (pure: sensors in, message out, so they're testable) -----------
def _cool(key, now):
    return now - _state["last"].get(key, 0) >= COOLDOWN[key]


def _said(key, now):
    _state["last"][key] = now


def check(s, now=None, procs=top_process):
    """Return a list of (kind, message) that should be said right now."""
    now = now or time.time()
    out = []
    b, charging = s["battery"], s["charging"]
    if charging:
        _state["bat_said"].clear()
        if b >= 100 and _cool("charged", now):
            _said("charged", now); out.append(("battery", "Battery is fully charged. You can unplug."))
    else:
        for step in BATTERY_STEPS:
            if b <= step and step not in _state["bat_said"]:
                _state["bat_said"].update(x for x in BATTERY_STEPS if x >= step)
                eta = f", about {s['mins']} minutes left" if s.get("mins") else ""
                out.append(("battery", f"Battery is at {b} percent{eta}. Please plug in."))
                break
    t = s.get("temp")
    _state["hot_run"] = _state["hot_run"] + 1 if t and t >= HOT_C else 0
    if _state["hot_run"] >= 2 and _cool("heat", now):
        _said("heat", now)
        p = procs("cpu")
        who = f" {p[0]} is using {int(p[1])} percent of the processor." if p and p[1] >= 40 else ""
        out.append(("heat", f"The processor is running hot at {t} degrees.{who}"))
    low = s["mem_mb"] is not None and s["mem_mb"] < LOW_MEM_MB
    swapped = s.get("swap_pct") is not None and s["swap_pct"] >= 90
    if (low or swapped) and _cool("memory", now):
        _said("memory", now)
        p = procs("mem")
        who = f" {p[0]} is using {p[2]} megabytes, the most." if p else ""
        out.append(("memory", f"Memory is running low, only {s['mem_mb']} megabytes free.{who} Closing something would help."))
    return out


def rain_alert(now=None, fetch=None):
    """Once an hour, peek at the forecast; speak if rain is likely in the next 3 hours."""
    now = now or time.time()
    if now - _state["rain_fetch"] < 3600 or not _cool("rain", now):
        return []
    _state["rain_fetch"] = now
    try:
        if fetch is None:
            import json, urllib.request
            with urllib.request.urlopen("https://wttr.in/?format=j1", timeout=10) as r:
                d = json.load(r)
        else:
            d = fetch()
    except Exception:
        return []
    hour = time.localtime(now).tm_hour * 100
    slots = [(int(h["time"]) + 2400 * i, h) for i, day in enumerate(d["weather"][:2]) for h in day["hourly"]]
    soon = [h for t, h in slots if hour - 100 <= t <= hour + 300]          # now .. +3h (forecast slots are 3-hourly)
    worst = max(soon, key=lambda h: int(h["chanceofrain"]), default=None)
    if worst and int(worst["chanceofrain"]) >= 70:
        _said("rain", now)
        t = int(worst["time"]) % 2400
        return [("rain", f"Rain is likely around {t // 100 % 12 or 12} {'AM' if t < 1200 else 'PM'}, "
                         f"{worst['chanceofrain']} percent. Take an umbrella.")]
    return []


class Watcher:
    """Call tick() often; it checks every CHECK_EVERY seconds and returns alerts to voice."""
    def __init__(self):
        self.next = time.time() + 20        # first look shortly after startup
        self.rain_thread = None
        self.rain_msgs = []

    def tick(self):
        if not enabled() or time.time() < self.next:
            return []
        self.next = time.time() + CHECK_EVERY
        alerts = []
        try:
            alerts += check(read_sensors())
        except Exception:
            pass
        if self.rain_msgs:                  # fetched in the background, delivered here
            alerts += self.rain_msgs; self.rain_msgs = []
        if snoozed():                       # "not now": only a nearly-dead battery gets through
            alerts = [a for a in alerts if a[0] == "battery" and re.search(r"\b(10|9|8|7|6|5|4|3|2|1) percent", a[1])]
        if not self.rain_thread or not self.rain_thread.is_alive():
            self.rain_thread = threading.Thread(target=lambda: self.rain_msgs.extend(rain_alert()), daemon=True)
            self.rain_thread.start()
        return alerts


def report():
    """Spoken one-breath system report ("status report")."""
    s = read_sensors()
    bits = [f"battery {s['battery']} percent{', charging' if s['charging'] else ''}"]
    if s["temp"]:
        bits.append(f"processor at {s['temp']} degrees")
    bits.append(f"{s['mem_mb']} megabytes of memory free")
    if s["swap_pct"] is not None and s["swap_pct"] >= 50:
        bits.append(f"swap {s['swap_pct']} percent full")
    p = top_process("mem")
    if p:
        bits.append(f"{p[0]} is the biggest app at {p[2]} megabytes")
    try:
        import json
        with open(os.path.join(os.path.dirname(__file__), "..", "hud", "stats.json")) as f:
            d = json.load(f)
        if d.get("wx_cond"):
            bits.append(f"outside it's {d['wx_temp'].lstrip('+')} and {d['wx_cond'].lower()}")
    except (OSError, ValueError):
        pass
    return ", ".join(bits)
