#!/usr/bin/env python3
"""
HeroHUD stats bridge.
Reads live system metrics from /proc and /sys and writes them to
hud/stats.json every second. The HUD front-end polls that file.
Pure standard library — no dependencies, works on any Linux.

Usage:  python3 overlay/stats.py [--interval 1.0] [--out ../hud/stats.json]
"""
import json, os, time, glob, argparse, shutil

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
def battery_info():
    base = first_glob("/sys/class/power_supply/BAT*")
    if not base:
        return 100, True  # desktop / no battery → report full & "powered"
    pct = read(os.path.join(base, "capacity"), "100")
    status = read(os.path.join(base, "status"), "Unknown")
    ac = read("/sys/class/power_supply/AC*/online") or read("/sys/class/power_supply/ACAD/online", "1")
    charging = status in ("Charging", "Full") or ac == "1"
    return int(pct) if pct.isdigit() else 100, charging


# ---- network (throughput + wifi) -------------------------------------------
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
            # SSID via iwgetid if available
            if shutil.which("iwgetid"):
                ssid = os.popen(f"iwgetid {wiface} -r 2>/dev/null").read().strip()
            break
    return round(down), round(up), signal, ssid, (iface or "")


def boot_ms():
    for line in read("/proc/stat").splitlines():
        if line.startswith("btime"):
            return int(line.split()[1]) * 1000
    return int((time.time() - float(read("/proc/uptime", "0").split()[0] or 0)) * 1000)


def sample():
    cpu = cpu_percent()
    mem_p, mem_u, mem_t = mem_info()
    disk_p, disk_u, disk_t = disk_info()
    batt, charging = battery_info()
    down, up, signal, ssid, iface = net_info()
    return {
        "cpu": round(cpu, 1), "freq": cpu_freq_ghz(),
        "mem": mem_p, "mem_used": mem_u, "mem_total": mem_t,
        "disk": disk_p, "disk_used": disk_u, "disk_total": disk_t,
        "battery": batt, "charging": charging,
        "down": down, "up": up, "signal": signal,
        "ssid": ssid or iface or "—", "iface": iface,
        "boot": boot_ms(), "ts": int(time.time() * 1000),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    tmp = args.out + ".tmp"
    cpu_percent()  # prime the delta
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
