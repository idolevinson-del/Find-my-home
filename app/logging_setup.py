import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def setup(level=logging.INFO):
    (ROOT / "data").mkdir(exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles + Hebrew
    except (AttributeError, ValueError):
        pass
    log = logging.getLogger("hunter")
    log.setLevel(level)
    if not log.handlers:
        for h in (logging.StreamHandler(sys.stdout),
                  logging.FileHandler(ROOT / "data" / "hunter.log", encoding="utf-8")):
            h.setFormatter(fmt)
            log.addHandler(h)
    return log
