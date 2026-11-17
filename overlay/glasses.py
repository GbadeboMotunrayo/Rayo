#!/usr/bin/python3
"""
Rayo <-> AIMB-G1 smart glasses (Cyan Glasses / QC "Oudmon" SDK family).

Runs on the SYSTEM python (needs python3-gi for BlueZ D-Bus); Rayo's voice
venv calls it as a subprocess. Every command prints one JSON line.

  glasses.py status            connected? battery, photos/videos/audio stored
  glasses.py photo             take a photo
  glasses.py video on|off      start / stop a video
  glasses.py audio on|off      start / stop an audio recording
  glasses.py police on|off     keep filming (restarting each clip) until "off"
  glasses.py sync              copy new media to ~/Pictures/Rayo Glasses in the background (PC offline 1-2 min)
  glasses.py ears on|off       glasses mic + speaker as Rayo's ears and voice (headset mode) / back to music mode

Protocol (decoded from the Cyan Glasses Android app, see ~/Desktop/Tech/rayo-glasses/PROTOCOL.md):
  BLE service de5bf728-…, write de5bf72a-…, notify de5bf729-…
  packet: BC <cmd> <len u16 LE> <crc16-modbus(payload) u16 LE> <payload>
"""
import json, os, signal, struct, subprocess, sys, time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

CONF = os.path.expanduser("~/.config/rayo")
STATE = os.path.join(CONF, "glasses-police.json")
LOG = os.path.join(CONF, "glasses.log")
W_UUID = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
N_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"
NAME_HINTS = ("AIMB", "G1_", "GLASS")          # how the glasses name themselves over Bluetooth

PHOTO, VIDEO_ON, VIDEO_OFF = b"\x02\x01\x01", b"\x02\x01\x02", b"\x02\x01\x03"
AUDIO_ON, AUDIO_OFF, COUNT = b"\x02\x01\x08", b"\x02\x01\x0c", b"\x02\x04"


def log(*a):
    os.makedirs(CONF, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(time.strftime("%F %T ") + " ".join(str(x) for x in a) + "\n")


def out(**kw):
    print(json.dumps(kw), flush=True)


def crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def packet(cmd, payload):
    return bytes([0xBC, cmd]) + struct.pack("<HH", len(payload), crc16(payload)) + payload


# ---- finding the glasses ----------------------------------------------------
def _objects(bus):
    return bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                         None, None, 0, -1, None).unpack()[0]


def find(bus):
    """-> (device_path, mac, write_char, notify_char) for connected glasses, or Nones."""
    objs = _objects(bus)
    dev = mac = None
    for path, ifs in objs.items():
        d = ifs.get("org.bluez.Device1")
        if d and d.get("Connected") and any(h in (d.get("Name") or "").upper() for h in NAME_HINTS):
            dev, mac = path, d.get("Address")
            break
    if not dev:
        return None, None, None, None
    w = n = None
    for path, ifs in objs.items():
        c = ifs.get("org.bluez.GattCharacteristic1")
        if c and path.startswith(dev + "/"):
            if c["UUID"] == W_UUID: w = path
            if c["UUID"] == N_UUID: n = path
    return dev, mac, w, n


def _poke_le(mac):
    """BlueZ only connects BLE to dual-mode glasses when something opens an LE link.
    Opening a raw ATT socket once makes it pick the link up and publish the GATT services."""
    import ctypes, socket
    class A(ctypes.Structure):
        _fields_ = [("family", ctypes.c_ushort), ("psm", ctypes.c_ushort), ("bdaddr", ctypes.c_ubyte * 6),
                    ("cid", ctypes.c_ushort), ("bdaddr_type", ctypes.c_ubyte)]
    def mk(m):
        a = A(); a.family, a.cid, a.bdaddr_type = 31, 4, 1
        for i, b in enumerate(reversed(m.split(":"))): a.bdaddr[i] = int(b, 16)
        return a
    libc = ctypes.CDLL(None, use_errno=True)
    s = socket.socket(31, socket.SOCK_SEQPACKET, 0)
    try:
        lo, re_ = mk("00:00:00:00:00:00"), mk(mac)
        libc.bind(s.fileno(), ctypes.byref(lo), ctypes.sizeof(lo))
        libc.connect(s.fileno(), ctypes.byref(re_), ctypes.sizeof(re_))
        time.sleep(1.5)
    finally:
        s.close()


class Glasses:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.dev, self.mac, self.w, self.n = find(self.bus)
        if self.dev and not (self.w and self.n):
            _poke_le(self.mac)
            for _ in range(20):                          # wait for BlueZ to publish the services
                time.sleep(0.5)
                self.dev, self.mac, self.w, self.n = find(self.bus)
                if self.w and self.n:
                    break
        self.ok = bool(self.w and self.n)
        self.inbox, self.on_event = [], None
        if self.ok:
            self.bus.signal_subscribe("org.bluez", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                      self.n, None, Gio.DBusSignalFlags.NONE, self._changed)
            try:
                self.bus.call_sync("org.bluez", self.n, "org.bluez.GattCharacteristic1", "StartNotify",
                                   None, None, 0, 5000, None)
            except GLib.Error:
                pass                                     # already notifying
            self.pump(0.3)

    def _changed(self, conn, sender, path, iface, sig, params):
        _, changed, _ = params.unpack()
        if "Value" in changed:
            p = bytes(changed["Value"])
            self.inbox.append(p)
            if self.on_event and len(p) > 6 and p[0] == 0xBC and p[1] == 0x73:
                self.on_event(p[6], p)

    def pump(self, secs):
        ctx, end = GLib.MainContext.default(), time.time() + secs
        while time.time() < end:
            while ctx.iteration(False):
                pass
            time.sleep(0.02)

    def send(self, cmd, payload, wait=1.5, want=None):
        """Send one packet; return the first reply for `want` (cmd byte) or None."""
        self.inbox.clear()
        pk = packet(cmd, payload)
        self.bus.call_sync("org.bluez", self.w, "org.bluez.GattCharacteristic1", "WriteValue",
                           GLib.Variant("(aya{sv})", (list(pk), {"type": GLib.Variant("s", "command")})),
                           None, 0, 5000, None)
        want = cmd if want is None else want
        end = time.time() + wait
        while time.time() < end:
            self.pump(0.05)
            for p in self.inbox:
                if len(p) > 1 and p[0] == 0xBC and p[1] == want:
                    return p
        return None

    def counts(self):
        r = self.send(0x41, COUNT)
        if r and len(r) >= 14 and r[7] == 4:
            return dict(photos=struct.unpack_from("<H", r, 8)[0], videos=struct.unpack_from("<H", r, 10)[0],
                        audio=struct.unpack_from("<H", r, 12)[0])
        return None

    def battery(self):
        r = self.send(0x42, b"\x00\x00")
        return r[6] if r and len(r) > 6 else None

    def control(self, payload):
        """-> (accepted, reply hex). Replies with error 0 or 255 both mean 'done' on this firmware."""
        r = self.send(0x41, payload, wait=3)
        if not r:
            return False, None
        err = r[9] if len(r) > 9 else 0
        return err in (0, 255), r.hex(" ")


def need():
    g = Glasses()
    if not g.ok:
        out(ok=False, msg="I can't reach your glasses. Are they on and connected?")
        sys.exit(0)
    return g


# ---- ears: glasses mic + speaker for Rayo ------------------------------------
def _card_and_profiles(mac):
    dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout or "[]")
    want = "bluez_card." + mac.replace(":", "_")
    for o in dump:
        if (o.get("info", {}).get("props", {}) or {}).get("device.name") == want:
            profs = {p.get("name"): p.get("index") for p in o["info"].get("params", {}).get("EnumProfile", [])}
            return o["id"], profs
    return None, {}


def _node(mac, cls):
    dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout or "[]")
    for o in dump:
        p = o.get("info", {}).get("props", {}) or {}
        if p.get("media.class") == cls and mac in (p.get("node.name") or "").replace("_", ":"):
            return o["id"]


def ears(on):
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    dev, mac, _, _ = find(bus)
    if not dev:
        return out(ok=False, msg="glasses not connected")
    card, profs = _card_and_profiles(mac)
    if card is None:
        return out(ok=False, msg="glasses have no audio device")
    name = "headset-head-unit" if on else "a2dp-sink"
    idx = profs.get(name) or profs.get(name + "-cvsd") or profs.get(name + "-sbc")
    subprocess.run(["wpctl", "set-profile", str(card), str(idx)], capture_output=True)
    time.sleep(2)
    if on:                                               # make them the default mic and speaker
        for cls in ("Audio/Source", "Audio/Sink"):
            nid = _node(mac, cls)
            if nid:
                subprocess.run(["wpctl", "set-default", str(nid)], capture_output=True)
    out(ok=True, msg="glasses are my ears now" if on else "glasses back to music mode")


# ---- police: film until told to stop -----------------------------------------
def _state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def police_on():
    st = _state()
    if st.get("pid") and _alive(st["pid"]):
        return out(ok=True, msg="already recording")
    g = need()
    ok, _ = g.control(VIDEO_ON)
    if not ok:
        return out(ok=False, msg="the glasses didn't start recording")
    del g
    # hand over to a background keeper that restarts each clip until "police off"
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_police_keeper"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    os.makedirs(CONF, exist_ok=True)
    with open(STATE, "w") as f:
        json.dump({"pid": p.pid, "since": time.time()}, f)
    log("police on, keeper", p.pid)
    out(ok=True, msg="recording. I'll keep filming until you say no police")


def police_keeper():
    """Runs in the background. While filming, the glasses send event 0x0b every 3 s
    (byte 7 = temperature, °C, seen 40 -> 57 in 75 s). If that heartbeat stops, or a clip
    is saved (event 0x01), the recording ended on its own: start the next one at once."""
    g = Glasses()
    st = {"clips": 0, "beat": time.time(), "temp": None, "restarts": 0}
    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(v=True))

    def restart(why):
        if stop["v"]:
            return
        st["restarts"] += 1
        log(f"police: {why} - restarting video (temp {st['temp']}°C)")
        g.control(VIDEO_ON)
        st["beat"] = time.time()

    def event(kind, p):
        if kind == 0x0b and len(p) > 7:
            st["beat"], st["temp"] = time.time(), p[7]
        elif kind == 0x01:
            st["clips"] += 1
            restart(f"clip {st['clips']} saved")

    g.on_event = event
    while not stop["v"] and g.ok:
        g.pump(1.0)
        if time.time() - st["beat"] > 8:               # no heartbeat: the glasses stopped filming
            restart("no recording heartbeat")
    if g.ok:
        g.control(VIDEO_OFF)
    log("police keeper ended:", st)


def police_off():
    st = _state()
    if st.get("pid") and _alive(st["pid"]):
        os.kill(st["pid"], signal.SIGTERM)
        for _ in range(30):
            if not _alive(st["pid"]):
                break
            time.sleep(0.2)
    try:
        os.remove(STATE)
    except FileNotFoundError:
        pass
    g = Glasses()
    if g.ok:
        g.control(VIDEO_OFF)
        c = g.counts()
        secs = int(time.time() - st.get("since", time.time()))
        took = f"{secs // 60} minutes" if secs >= 120 else ("a minute" if secs >= 60 else f"{secs} seconds")
        log("police off", c)
        return out(ok=True, msg=f"stopped. {took} filmed, saved on your glasses" if st else "stopped recording")
    out(ok=True, msg="stopped")


# ---- sync: copy the media off the glasses -------------------------------------
# The tested sync lives in ~/Desktop/Tech/rayo-glasses/glasses.py (hotspot import 02 01 04 02,
# joins the glasses' Wi-Fi, downloads /files/*, rejoins the previous Wi-Fi). We run it in the
# background: the PC is offline for 1-2 minutes while it runs.
SYNC_SCRIPT = os.path.expanduser(os.environ.get("RAYO_GLASSES_SYNC", "~/Desktop/Tech/rayo-glasses/glasses.py"))
SYNC_LOCK = os.path.join(CONF, "glasses-sync.json")
DEST = os.path.expanduser("~/Pictures/Rayo Glasses")


def _notify(msg):
    subprocess.run(["notify-send", "-a", "Rayo", "-i", "camera-photo", "Rayo · glasses", msg], capture_output=True)


def sync_start():
    try:
        with open(SYNC_LOCK) as f:
            pid = json.load(f).get("pid")
        if pid and _alive(pid):
            return out(ok=True, msg="already syncing your glasses")
    except Exception:
        pass
    if not os.path.exists(SYNC_SCRIPT):
        return out(ok=False, msg="I can't find the glasses sync script")
    if _state().get("pid") and _alive(_state()["pid"]):
        return out(ok=False, msg="not while police recording is on")
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_sync_runner"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    os.makedirs(CONF, exist_ok=True)
    with open(SYNC_LOCK, "w") as f:
        json.dump({"pid": p.pid, "since": time.time()}, f)
    out(ok=True, msg="syncing your glasses. I'll be offline for a minute or two, and I'll tell you when it's done")


def sync_runner():
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, SYNC_SCRIPT, "sync"], capture_output=True, text=True, timeout=1800)
        text = (r.stdout + r.stderr).strip()
        log("sync exit", r.returncode, text[-600:])
        import re
        m = re.search(r"saved (\d+) file", text)
        n = int(m.group(1)) if m else None
        if r.returncode == 0 and n is not None:
            msg = (f"glasses synced: {n} new file{'s' if n != 1 else ''} in Pictures › Rayo Glasses"
                   if n else "glasses synced: nothing new")
        else:
            reason = text.splitlines()[-1] if text else f"exit {r.returncode}"
            msg = "glasses sync failed: " + re.sub(r"^glasses:\s*", "", reason)   # script prints "glasses: <reason>"
    except subprocess.TimeoutExpired:
        msg = "glasses sync took too long and was stopped"
        log("sync timeout")
    finally:
        try:
            os.remove(SYNC_LOCK)
        except FileNotFoundError:
            pass
    log(msg, f"({int(time.time() - t0)}s)")
    _notify(msg)


# ---- main --------------------------------------------------------------------
def main(argv):
    what = argv[1] if len(argv) > 1 else "status"
    arg = argv[2] if len(argv) > 2 else ""
    if what == "ears":
        return ears(arg != "off")
    if what == "police":
        return police_off() if arg == "off" else police_on()
    if what == "_police_keeper":
        return police_keeper()
    if what == "sync":
        return sync_start()
    if what == "_sync_runner":
        return sync_runner()
    g = need()
    if what == "status":
        c, b = g.counts(), g.battery()
        bits = [f"battery {b}%"] if b is not None else []
        if c:
            bits.append(f"{c['photos']} photos, {c['videos']} videos and {c['audio']} recordings on them")
        return out(ok=True, msg="glasses: " + ", ".join(bits), battery=b, counts=c)
    if what == "photo":
        before = g.counts()
        ok, raw = g.control(PHOTO)
        g.pump(2.5)
        after = g.counts()
        took = bool(before and after and after["photos"] > before["photos"])
        if not took:                                     # the save can lag a moment behind the reply
            g.pump(3)
            after = g.counts()
            took = bool(before and after and after["photos"] > before["photos"])
        log("photo", ok, raw, before, after)
        busy = bool(raw) and raw.split()[-1] == "04"     # state 4: busy (e.g. a Wi-Fi file transfer)
        msg = "got it" if took else ("the glasses are busy right now, try again in a moment" if busy
                                     else "the glasses didn't take it")
        return out(ok=took, msg=msg, counts=after)
    if what in ("video", "audio"):
        on = arg != "off"
        payload = {("video", True): VIDEO_ON, ("video", False): VIDEO_OFF,
                   ("audio", True): AUDIO_ON, ("audio", False): AUDIO_OFF}[(what, on)]
        ok, raw = g.control(payload)
        log(what, arg, ok, raw)
        words = {("video", True): "recording video", ("video", False): "video saved",
                 ("audio", True): "recording audio", ("audio", False): "audio saved"}[(what, on)]
        return out(ok=bool(ok), msg=words if ok else "the glasses didn't respond")
    out(ok=False, msg=f"unknown glasses command {what}")


if __name__ == "__main__":
    main(sys.argv)
