"""Background scanner: runs a scan every N minutes, plus on-demand 'Scan now'.

A lock guarantees scans never overlap (Scan now during a scheduled scan is a no-op).
"""
import logging
import threading
import time

from app import config, pipeline

log = logging.getLogger("hunter")


class Scanner:
    def __init__(self, conn):
        self.conn = conn
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.running = False
        self.next_scan_at = None

    def scan(self):
        if not self._lock.acquire(blocking=False):
            log.info("Scan already running — skipped")
            return None
        self.running = True
        try:
            return pipeline.run_cycle(self.conn, config.load_settings())
        except Exception as e:
            log.exception(f"Scan failed: {e}")
            return None
        finally:
            self.running = False
            self._lock.release()

    def scan_now(self):
        """Trigger a scan in the background thread; returns immediately."""
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            self.scan()
            minutes = config.scan_interval_minutes(config.load_settings())
            self.next_scan_at = time.time() + minutes * 60
            log.info(f"Next scan in {minutes:g} min")
            self._wake.wait(minutes * 60)
            self._wake.clear()

    def start(self):
        threading.Thread(target=self._loop, name="scanner", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._wake.set()
