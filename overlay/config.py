"""Rayo's user settings: ~/.config/rayo/config.json (created on first save).

{"brain": {"model": "gemma3:1b"}, "speech": {"on": true, "voice": "en_GB-alan-medium"}}
"""
import os, json

PATH = os.path.expanduser("~/.config/rayo/config.json")


def load():
    try:
        with open(PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get(section, key, default=None):
    return load().get(section, {}).get(key, default)


def _write(cfg):
    """Settings and usage stats are private to you: folder 700, file 600."""
    d = os.path.dirname(PATH)
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    tmp = PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, PATH)


def set(section, key, value):
    cfg = load()
    cfg.setdefault(section, {})[key] = value
    _write(cfg)


def update(section, values):
    """Set several keys of one section in a single write."""
    cfg = load()
    cfg.setdefault(section, {}).update(values)
    _write(cfg)
