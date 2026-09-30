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


def set(section, key, value):
    cfg = load()
    cfg.setdefault(section, {})[key] = value
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, PATH)


def update(section, values):
    """Set several keys of one section in a single write."""
    cfg = load()
    cfg.setdefault(section, {}).update(values)
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, PATH)
