"""Settings (config.yaml) and secrets (.env).

Settings are non-secret and editable from the UI, which rewrites config.yaml.
Secrets only ever come from the environment / .env and are never written to disk.
"""
import copy
import os
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("APP_CONFIG", ROOT / "config.yaml"))
MIN_SCAN_INTERVAL = 5  # minutes — floor so we never hammer Yad2

_lock = threading.Lock()


def load_dotenv(path=ROOT / ".env"):
    """Minimal KEY=VALUE .env loader. Real environment variables win."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def secret(name):
    v = os.environ.get(name, "").strip()
    return v or None


def load_settings(path=None):
    with _lock:
        with open(path or CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}


def save_settings(settings, path=None):
    with _lock:
        tmp = Path(path or CONFIG_PATH).with_suffix(".yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(settings, f, allow_unicode=True, sort_keys=False)
        tmp.replace(path or CONFIG_PATH)


def merge_settings(current, patch):
    """Deep-merge a partial settings dict from the UI into the current settings."""
    out = copy.deepcopy(current)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge_settings(out[k], v)
        else:
            out[k] = v
    return out


def scan_interval_minutes(settings):
    env = os.environ.get("SCAN_INTERVAL_MINUTES")
    try:
        minutes = float(env) if env else float(settings.get("schedule", {}).get("scan_interval_minutes", 15))
    except ValueError:
        minutes = 15
    return max(MIN_SCAN_INTERVAL, minutes)
