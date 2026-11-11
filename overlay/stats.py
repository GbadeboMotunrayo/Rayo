#!/usr/bin/env python3
"""
Rayo stats bridge.
Reads live system metrics from /proc and /sys and writes them to
hud/stats.json every second. The HUD front-end polls that file.
Pure standard library — no dependencies, works on any Linux.

Usage:  python3 overlay/stats.py [--interval 1.0] [--out ../hud/stats.json]
"""
import json, os, re, time, glob, argparse, shutil, threading, socket, sqlite3, subprocess, urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.normpath(os.path.join(HERE, "..", "hud", "stats.json"))


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def first_glob(pattern):
    m = glob.glob(pattern)
    return m[0] if m else None


# ---- CPU (delta of /proc/stat) ---------------------------------------------
_prev_cpu = None
def cpu_percent():
    global _prev_cpu
    fields = read("/proc/stat").splitlines()[0].split()[1:]
    vals = list(map(int, fields[:7]))
    idle = vals[3] + vals[4]
    total = sum(vals)
    if _prev_cpu is None:
        _prev_cpu = (idle, total)
        return 0.0
    di = idle - _prev_cpu[0]
    dt = total - _prev_cpu[1]
    _prev_cpu = (idle, total)
    return 0.0 if dt <= 0 else max(0.0, min(100.0, (1 - di / dt) * 100))


def cpu_freq_ghz():
    # average current freq across cores
    fs = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")
    khz = [int(read(f, "0")) for f in fs if read(f, "0").isdigit()]
    if khz:
        return round(sum(khz) / len(khz) / 1e6, 2)
    # fallback: /proc/cpuinfo MHz
    for line in read("/proc/cpuinfo").splitlines():
        if line.lower().startswith("cpu mhz"):
            try:
                return round(float(line.split(":")[1]) / 1000, 2)
            except ValueError:
                pass
    return 0.0


# ---- memory -----------------------------------------------------------------
def mem_info():
    info = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        info[k] = int(v.split()[0])  # kB
    total = info.get("MemTotal", 1)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used = total - avail
    gib = lambda kb: round(kb / 1024 / 1024, 1)
    return round(used / total * 100, 1), gib(used), gib(total)


# ---- disk (root fs) ---------------------------------------------------------
def disk_info(path="/"):
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - free
    gib = lambda b: round(b / 1024 ** 3)
    return round(used / total * 100, 1), gib(used), gib(total)


# ---- battery ----------------------------------------------------------------
def _num(path):
    v = read(path)
    try:
        return float(v)
    except ValueError:
        return None

def battery_info():
    """Return (percent, charging, status, minutes_remaining_or_None)."""
    base = first_glob("/sys/class/power_supply/BAT*")
    if not base:
        return 100, True, "AC", None  # desktop / no battery
    pct = read(os.path.join(base, "capacity"), "100")
    status = read(os.path.join(base, "status"), "Unknown")
    ac = read("/sys/class/power_supply/AC*/online") or read("/sys/class/power_supply/ACAD/online", "")
    charging = status == "Charging" or (status != "Discharging" and ac == "1")

    # time estimate: prefer charge_* (µAh, µA); fall back to energy_* (µWh, µW)
    now = _num(os.path.join(base, "charge_now"))
    full = _num(os.path.join(base, "charge_full"))
    rate = _num(os.path.join(base, "current_now"))
    if now is None:
        now = _num(os.path.join(base, "energy_now"))
        full = _num(os.path.join(base, "energy_full"))
        rate = _num(os.path.join(base, "power_now"))

    minutes = None
    if rate and rate > 0 and now is not None and full is not None:
        if status == "Charging":
            minutes = round((full - now) / rate * 60)
        elif status == "Discharging":
            minutes = round(now / rate * 60)
        if minutes is not None and minutes < 0:
            minutes = None
    if status == "Full":
        minutes = 0

    p = int(pct) if pct.isdigit() else 100
    return p, charging, status, minutes


# ---- fan (tacho RPM) --------------------------------------------------------
def fan_info():
    """Return (rpm, max_rpm, label). Scans every hwmon for a fan tacho. On this
    Dell the fan shows up under both dell_ddv (has the 'CPU Fan' label) and
    dell_smm (has fan1_max), so we merge: highest RPM seen, any max, any label."""
    rpm = mx = 0
    lbl = ""
    for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        for f in sorted(glob.glob(os.path.join(h, "fan*_input"))):
            v = read(f)
            if not v.isdigit():
                continue
            rpm = max(rpm, int(v))
            m = read(f.replace("_input", "_max"))
            if m.isdigit():
                mx = max(mx, int(m))
            l = read(f.replace("_input", "_label"))
            if l and not lbl:
                lbl = l
    if not mx:
        mx = 8100          # sensible XPS-9315 default so the gauge still scales
    return rpm, mx, (lbl or "FAN")


# ---- network (throughput + wifi) -------------------------------------------
def _resolve_ssid(iface):
    """Best-effort network NAME (not the interface id). Tries iwgetid, then
    `iw dev link`, then nmcli — whichever yields a name first."""
    if shutil.which("iwgetid"):
        s = os.popen(f"iwgetid {iface} -r 2>/dev/null").read().strip()
        if s:
            return s
    if shutil.which("iw"):
        for line in os.popen(f"iw dev {iface} link 2>/dev/null").read().splitlines():
            line = line.strip()
            if line.startswith("SSID:"):
                return line.split("SSID:", 1)[1].strip()
    if shutil.which("nmcli"):
        for line in os.popen("nmcli -t -f active,ssid dev wifi 2>/dev/null").read().splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1].strip()
    return ""


_prev_net = None
def net_info():
    global _prev_net
    # pick the default route interface
    iface = None
    for line in read("/proc/net/route").splitlines()[1:]:
        p = line.split()
        if len(p) > 1 and p[1] == "00000000":
            iface = p[0]; break
    down = up = 0.0
    now = time.time()
    if iface:
        for line in read("/proc/net/dev").splitlines():
            if line.strip().startswith(iface + ":"):
                p = line.split(":")[1].split()
                rx, tx = int(p[0]), int(p[8])
                if _prev_net and _prev_net[0] == iface:
                    dt = now - _prev_net[3] or 1
                    down = max(0, (rx - _prev_net[1]) / dt)
                    up = max(0, (tx - _prev_net[2]) / dt)
                _prev_net = (iface, rx, tx, now)
                break
    # wifi link quality + SSID
    signal, ssid = 0, ""
    for line in read("/proc/net/wireless").splitlines()[2:]:
        p = line.split()
        if p:
            wiface = p[0].rstrip(":")
            try:
                signal = round(float(p[2].rstrip(".")) / 70 * 100)
            except (IndexError, ValueError):
                signal = 0
            ssid = _resolve_ssid(wiface)
            break
    return round(down), round(up), signal, ssid, (iface or "")


# ---- cpu temperature --------------------------------------------------------
def cpu_temp():
    """CPU package temperature in °C (thermal zone, then coretemp hwmon)."""
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        if read(os.path.join(z, "type")) in ("x86_pkg_temp", "cpu-thermal", "acpitz"):
            v = read(os.path.join(z, "temp"))
            if v.isdigit():
                return round(int(v) / 1000)
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(os.path.join(h, "name")) == "coretemp":
            for lab in glob.glob(os.path.join(h, "temp*_label")):
                if "Package" in read(lab):
                    v = read(lab.replace("_label", "_input"))
                    if v.isdigit():
                        return round(int(v) / 1000)
    return None


# ---- monthly data usage (self-accumulating, survives reboots) --------------
# There is no built-in "data used this month" counter on Linux (/proc counters
# reset on reboot / interface down). vnstat would need a daemon + sudo, so we
# keep our own tally: each tick we add the positive delta of the default iface's
# rx+tx to a per-month total persisted at ~/.local/share/rayo/usage.json.
# Caveat: it counts traffic while Rayo is running.
_USAGE_DIR = os.path.expanduser("~/.local/share/rayo")
_USAGE_FILE = os.path.join(_USAGE_DIR, "usage.json")
_usage = {"month": None, "bytes": 0, "last": None, "loaded": False, "flushed": 0.0}

def _iface_total_bytes(iface):
    for line in read("/proc/net/dev").splitlines():
        if line.strip().startswith(iface + ":"):
            p = line.split(":")[1].split()
            try:
                return int(p[0]) + int(p[8])      # rx + tx (bytes, since boot)
            except (IndexError, ValueError):
                return None
    return None

def monthly_usage(iface):
    month = time.strftime("%Y-%m")
    if not _usage["loaded"]:
        try:
            with open(_USAGE_FILE) as f:
                d = json.load(f)
            if d.get("month") == month:
                _usage["bytes"] = int(d.get("bytes", 0))
        except Exception:
            pass
        _usage["loaded"] = True
        _usage["month"] = month
    if _usage["month"] != month:                  # new month → reset
        _usage.update(month=month, bytes=0, last=None)
    if iface:
        cur = _iface_total_bytes(iface)
        if cur is not None:
            if _usage["last"] is not None:
                delta = cur - _usage["last"]
                if delta > 0:                     # ignore counter resets
                    _usage["bytes"] += delta
            _usage["last"] = cur
    now = time.time()
    if now - _usage["flushed"] > 15:              # flush at most every 15s
        _usage["flushed"] = now
        try:
            os.makedirs(_USAGE_DIR, exist_ok=True)
            tmp = _USAGE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"month": _usage["month"], "bytes": _usage["bytes"]}, f)
            os.replace(tmp, _USAGE_FILE)
        except Exception:
            pass
    return _usage["bytes"]


# ---- weather (wttr.in, non-blocking, cached ~15 min) -----------------------
_wx = {"ts": 0.0, "data": {}, "busy": False}
def _wx_refresh():
    try:
        req = urllib.request.Request(
            "https://wttr.in/?format=%l|%t|%C|%f",
            headers={"User-Agent": "curl/8"})  # curl UA → plain text, not HTML
        raw = urllib.request.urlopen(req, timeout=6).read().decode("utf-8").strip()
        loc, temp, cond, feels = (raw.split("|") + ["", "", "", ""])[:4]
        if temp:
            _wx["data"] = {"wx_loc": loc, "wx_temp": temp, "wx_cond": cond, "wx_feels": feels}
    except Exception:
        pass
    finally:
        _wx["busy"] = False

def weather():
    now = time.time()
    if not _wx["busy"] and now - _wx["ts"] > 900:   # refresh at most every 15 min
        _wx["ts"] = now
        _wx["busy"] = True
        threading.Thread(target=_wx_refresh, daemon=True).start()
    return _wx["data"]


def boot_ms():
    for line in read("/proc/stat").splitlines():
        if line.startswith("btime"):
            return int(line.split()[1]) * 1000
    return int((time.time() - float(read("/proc/uptime", "0").split()[0] or 0)) * 1000)


# ---- background checks: each runs on its own slow clock, never in the 1 s tick
def _every(seconds, fn, store):
    """Run fn() now and then every `seconds` on a daemon thread; keep its result in store."""
    def loop():
        while True:
            try:
                store.update(fn() or {})
            except Exception:
                pass
            time.sleep(seconds)
    threading.Thread(target=loop, daemon=True).start()


def _rayo_config():
    try:
        with open(os.path.expanduser("~/.config/rayo/config.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _port_open(port):
    try:
        socket.create_connection(("127.0.0.1", int(port)), timeout=0.6).close()
        return True
    except (OSError, ValueError):
        return False


# THREAT: the read-only audit in security/security-check.sh (about 2 s), every 15 min
_SEC = os.path.normpath(os.path.join(HERE, "..", "security", "security-check.sh"))
_threat = {}
def _check_threat():
    if not os.path.exists(_SEC):
        return {"threat": None}
    r = subprocess.run(["nice", "-n", "15", _SEC], capture_output=True, text=True, timeout=120)
    out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)
    m = re.search(r"Result:\s*(\d+) problem\(s\),\s*(\d+) warning\(s\)", out)
    if not m:
        return {"threat": None}
    first = next((l.strip()[2:] for l in out.splitlines() if l.strip().startswith("✗")), "")
    return {"threat": {"bad": int(m.group(1)), "warn": int(m.group(2)), "first": first[:90],
                       "at": int(time.time())}}


# OFFICE: the MG Office feed through the mgoffice tunnel, every 30 s. Needs the
# office key in ~/.config/rayo/config.json → {"office": {"key": "..."}}. The key
# is only sent to 127.0.0.1 (the tunnel); it never goes into stats.json.
_office = {}
def _check_office():
    o = _rayo_config().get("office") or {}
    port = int(o.get("port") or 0)
    if not port:
        return {"office": None}
    if not _port_open(port):
        return {"office": {"state": "closed"}}
    if not o.get("key"):
        return {"office": {"state": "nokey"}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/hud",
                                 headers={"Authorization": "Bearer " + str(o["key"])})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
    except urllib.error.HTTPError as e:
        return {"office": {"state": "badkey" if e.code == 401 else "error"}}
    except Exception:
        return {"office": {"state": "error"}}
    gw = [s for s in d.get("staff", []) if s.get("gateway")]
    need = d.get("attention") or []
    names = {s.get("id"): s.get("name") for s in d.get("staff", [])}
    _office_notify(need, gw, names, port)
    top = need[0] if need else None
    return {"office": {"state": "ok", "need": len(need),
                       "on": sum(1 for s in gw if s.get("status") == "active"), "of": len(gw),
                       "top": ({"title": (top.get("title") or "")[:70], "who": names.get(top.get("assignee"), "")}
                               if top else None),
                       "done_24h": (d.get("task_summary") or {}).get("done_24h", 0)}}


# Desktop notifications for the Office: something new needs you, or a staff
# member's gateway goes down / comes back. What has already been announced is
# kept in ~/.local/share/rayo/office_seen.json, so a restart doesn't repeat it.
# Quiet while Rayo's alerts are snoozed ("not now"); GNOME's Do Not Disturb
# hides the banners as usual. Clicking "Open the Office" opens it.
_SEEN_FILE = os.path.join(_USAGE_DIR, "office_seen.json")
_ICON = os.path.normpath(os.path.join(HERE, "..", "hud", "favicon.svg"))

def _notify(title, body, url=None, urgent=False):
    if not shutil.which("notify-send"):
        return
    argv = ["notify-send", "-a", "Rayo", "-i", _ICON, "-u", "critical" if urgent else "normal", title, body]
    if not url:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    def wait_click():          # --wait prints the action's name when you click it
        try:
            r = subprocess.run(argv[:1] + ["--action=open=Open the Office", "--wait"] + argv[1:],
                               capture_output=True, text=True, timeout=3600)
            if r.stdout.strip() == "open":
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        except (OSError, subprocess.TimeoutExpired):
            pass
    threading.Thread(target=wait_click, daemon=True).start()

def _office_notify(need, gw, names, port):
    try:
        with open(_SEEN_FILE) as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = None
    ids = {t.get("id") for t in need if t.get("id")}
    off = {s.get("id") for s in gw if s.get("status") != "active"}
    url = f"http://localhost:{port}"
    snoozed = time.time() < float((_rayo_config().get("awareness") or {}).get("snooze_until", 0) or 0)
    if seen is None:           # first time connected: one summary, not a burst
        n = len(ids)
        _notify("The Office is connected",
                f"{n} thing{'s' if n != 1 else ''} need{'s' if n == 1 else ''} you right now." if n else "Nothing needs you right now.",
                url if n else None)
    elif not snoozed:
        for t in need:
            if t.get("id") and t["id"] not in seen.get("need", []):
                who = names.get(t.get("assignee"), "Someone")
                why = (t.get("why") or "").strip()
                _notify(f"{who} needs you", (t.get("title") or "A task is blocked") + (f"\n{why[:160]}" if why else ""),
                        url, urgent=True)
        for sid in off - set(seen.get("off", [])):
            _notify(f"{names.get(sid, sid)} went offline", "Their gateway on the server is down.", url)
        for sid in set(seen.get("off", [])) - off:
            _notify(f"{names.get(sid, sid)} is back online", "Their gateway is running again.")
    try:
        os.makedirs(_USAGE_DIR, exist_ok=True)
        with open(_SEEN_FILE + ".tmp", "w") as f:
            json.dump({"need": sorted(ids), "off": sorted(off)}, f)
        os.replace(_SEEN_FILE + ".tmp", _SEEN_FILE)
    except OSError:
        pass


# NEXT EVENT: the GNOME calendar store (Evolution data server), read straight
# from its files, every 5 min. Empty until a calendar is added in Settings →
# Online Accounts. One-off events only: repeating events are skipped for now.
_cal = {}
def _ics_when(v):
    v = v.strip()
    try:
        if len(v) == 8:                                       # all-day: YYYYMMDD
            return datetime.strptime(v, "%Y%m%d").astimezone(), True
        if v.endswith("Z"):
            return datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(), False
        return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").astimezone(), False
    except ValueError:
        return None, False

def _events_from_ics(text):
    text = re.sub(r"\r?\n[ \t]", "", text)                    # unfold long lines
    for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        if re.search(r"^RRULE", blk, re.M):
            continue
        m = re.search(r"^DTSTART[^:\n]*:(.+)$", blk, re.M)
        t = re.search(r"^SUMMARY[^:\n]*:(.*)$", blk, re.M)
        if m:
            when, allday = _ics_when(m.group(1))
            if when:
                yield when, allday, (t.group(1).strip() if t else "").replace("\\,", ",")[:60]

def _check_calendar():
    now = datetime.now().astimezone()
    soon = []
    for f in glob.glob(os.path.expanduser("~/.local/share/evolution/calendar/*/calendar.ics")):
        try:
            soon += list(_events_from_ics(open(f, encoding="utf-8", errors="ignore").read()))
        except OSError:
            pass
    for db in glob.glob(os.path.expanduser("~/.cache/evolution/calendar/*/cache.db")):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
            for (obj,) in con.execute("SELECT ECacheOBJ FROM ECacheObjects"):
                soon += list(_events_from_ics(obj or ""))
            con.close()
        except sqlite3.Error:
            pass
    ahead = sorted((e for e in soon if e[0] >= now - timedelta(minutes=10) and e[0] <= now + timedelta(hours=36)),
                   key=lambda e: e[0])
    if not ahead:
        return {"next_event": None}
    when, allday, title = ahead[0]
    return {"next_event": {"at": int(when.timestamp() * 1000), "allday": allday, "title": title or "Untitled"}}


def start_checks():
    _every(900, _check_threat, _threat)
    _every(30, _check_office, _office)
    _every(300, _check_calendar, _cal)


# SYS: one honest word for the machine, from this tick's readings
def sys_state(cpu, mem, temp, batt, charging):
    if temp is not None and temp >= 92:
        return "HOT"
    if not charging and batt <= 10:
        return "LOW POWER"
    if mem >= 92:
        return "MEMORY FULL"
    if cpu >= 90:
        return "UNDER LOAD"
    return "NOMINAL"


def link_state(iface):
    """SECURE LINK = the mgoffice tunnel to the MG server is up."""
    if not iface:
        return "OFFLINE"
    port = (_rayo_config().get("office") or {}).get("port")
    if not port:
        return "NO TUNNEL SET"
    return "ACTIVE" if _port_open(port) else "CLOSED"


def sample():
    cpu = cpu_percent()
    mem_p, mem_u, mem_t = mem_info()
    disk_p, disk_u, disk_t = disk_info()
    batt, charging, batt_status, batt_min = battery_info()
    down, up, signal, ssid, iface = net_info()
    fan_rpm, fan_max, fan_label = fan_info()
    temp = cpu_temp()
    return {
        "cpu": round(cpu, 1), "freq": cpu_freq_ghz(),
        "mem": mem_p, "mem_used": mem_u, "mem_total": mem_t,
        "disk": disk_p, "disk_used": disk_u, "disk_total": disk_t,
        "battery": batt, "charging": charging,
        "batt_status": batt_status, "batt_min": batt_min,
        "fan": fan_rpm, "fan_max": fan_max, "fan_label": fan_label,
        "cpu_temp": temp,
        "sys_state": sys_state(cpu, mem_p, temp, batt, charging),
        "link": link_state(iface),
        **_threat, **_office, **_cal,
        "down": down, "up": up, "signal": signal,
        "month_bytes": monthly_usage(iface),
        "ssid": ssid or iface or "—", "iface": iface,
        "boot": boot_ms(), "ts": int(time.time() * 1000),
        **weather(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    tmp = args.out + ".tmp"
    cpu_percent()  # prime the delta
    start_checks()
    while True:
        try:
            data = sample()
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, args.out)  # atomic
        except Exception as e:
            # never die on a transient read error
            pass
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
