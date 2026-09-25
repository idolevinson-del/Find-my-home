"""SQLite storage: listings, change history, notification outbox, scan log.

Booleans are stored as 1 / 0 / NULL so "unknown" (NULL) survives the round trip.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import Listing, Status

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("APP_DB", ROOT / "data" / "hunter.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT,
    url TEXT NOT NULL,
    title TEXT, city TEXT, neighborhood TEXT, street TEXT,
    price INTEGER, rooms REAL, size_sqm REAL, floor INTEGER,
    property_type TEXT, description TEXT, images TEXT,
    parking INTEGER, balcony INTEGER, elevator INTEGER, furnished INTEGER,
    is_broker INTEGER,
    lat REAL, lon REAL,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEW',
    status_changed_at TEXT,
    passes_filters INTEGER,
    filter_reasons TEXT,
    area_group TEXT,
    match_score INTEGER,
    score_breakdown TEXT,
    ai_analysis TEXT,
    ai_analyzed_at TEXT,
    raw_json TEXT
);
-- Dedup key: (source, source_id); URL is the fallback when a source has no id.
CREATE UNIQUE INDEX IF NOT EXISTS ux_listings_source_id
    ON listings(source, source_id) WHERE source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_listings_source_url
    ON listings(source, url) WHERE source_id IS NULL;

CREATE TABLE IF NOT EXISTS listing_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    field TEXT NOT NULL,
    old_value TEXT, new_value TEXT,
    changed_at TEXT NOT NULL
);

-- Outbox: one row per (listing, kind). A failed send stays 'pending' and is retried.
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    channel TEXT NOT NULL DEFAULT 'telegram',
    kind TEXT NOT NULL DEFAULT 'new_listing',
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | sent | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE (listing_id, channel, kind)
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT,
    fetched INTEGER, passed INTEGER, new INTEGER, updated INTEGER,
    notified INTEGER, error TEXT
);
"""

BOOL_FIELDS = ("parking", "balcony", "elevator", "furnished", "is_broker")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    path = Path(path or DB_PATH)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _to_db(field, value):
    if field in BOOL_FIELDS:
        return None if value is None else int(bool(value))
    if field == "images":
        return json.dumps(value or [], ensure_ascii=False)
    return value


def _find(conn, listing):
    if listing.source_id:
        return conn.execute("SELECT * FROM listings WHERE source=? AND source_id=?",
                            (listing.source, listing.source_id)).fetchone()
    return conn.execute("SELECT * FROM listings WHERE source=? AND url=? AND source_id IS NULL",
                        (listing.source, listing.url)).fetchone()


def upsert_listing(conn, listing: Listing, raw=None):
    """Insert or update. Returns (listing_id, outcome) where outcome is 'new' | 'updated' | 'unchanged'.

    For an existing listing, changed tracked fields are written and logged to
    listing_changes. A field that became unknown (None) in this scan does not
    overwrite a value we already know.
    """
    ts = now()
    row = _find(conn, listing)
    data = listing.to_dict()
    if row is None:
        cols = [c for c in data if c != "source_id" or listing.source_id is not None]
        values = [_to_db(c, data[c]) for c in cols]
        cols += ["first_seen_at", "last_seen_at", "last_updated_at", "status", "raw_json"]
        values += [ts, ts, ts, Status.NEW, json.dumps(raw, ensure_ascii=False) if raw else None]
        cur = conn.execute(f"INSERT INTO listings ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                           values)
        conn.commit()
        return cur.lastrowid, "new"

    changes = {}
    for f in Listing.TRACKED + ("images", "neighborhood", "street", "property_type"):
        new = _to_db(f, data.get(f))
        if new is None or (f == "images" and new == "[]"):
            continue
        if row[f] != new:
            changes[f] = (row[f], new)
    conn.execute("UPDATE listings SET last_seen_at=? WHERE id=?", (ts, row["id"]))
    if changes:
        conn.execute(f"UPDATE listings SET {', '.join(f'{f}=?' for f in changes)}, last_updated_at=? WHERE id=?",
                     [v[1] for v in changes.values()] + [ts, row["id"]])
        conn.executemany(
            "INSERT INTO listing_changes (listing_id, field, old_value, new_value, changed_at) VALUES (?,?,?,?,?)",
            [(row["id"], f, None if o is None else str(o), str(n), ts)
             for f, (o, n) in changes.items() if f not in ("images",)])
    conn.commit()
    return row["id"], ("updated" if changes else "unchanged")


def row_to_listing(row) -> Listing:
    kw = {f: row[f] for f in Listing.__dataclass_fields__ if f in row.keys()}
    for f in BOOL_FIELDS:
        kw[f] = None if kw.get(f) is None else bool(kw[f])
    kw["images"] = json.loads(row["images"] or "[]")
    return Listing(**kw)


def row_to_api(row):
    d = dict(row)
    for f in BOOL_FIELDS + ("passes_filters",):
        d[f] = None if d.get(f) is None else bool(d[f])
    for f in ("images", "filter_reasons", "score_breakdown", "ai_analysis"):
        d[f] = json.loads(d[f]) if d.get(f) else ([] if f in ("images", "filter_reasons") else None)
    d.pop("raw_json", None)
    return d


def set_evaluation(conn, listing_id, passes, reasons, area_group, score, breakdown):
    conn.execute(
        "UPDATE listings SET passes_filters=?, filter_reasons=?, area_group=?, match_score=?, score_breakdown=? WHERE id=?",
        (int(passes), json.dumps(reasons, ensure_ascii=False), area_group, score,
         json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None, listing_id))
    conn.commit()


def set_ai_analysis(conn, listing_id, analysis):
    conn.execute("UPDATE listings SET ai_analysis=?, ai_analyzed_at=? WHERE id=?",
                 (json.dumps(analysis, ensure_ascii=False), now(), listing_id))
    conn.commit()


def set_status(conn, listing_id, status):
    if status not in Status.ALL:
        raise ValueError(f"unknown status {status}")
    cur = conn.execute("UPDATE listings SET status=?, status_changed_at=? WHERE id=?", (status, now(), listing_id))
    conn.commit()
    return cur.rowcount > 0


def get_listing(conn, listing_id):
    return conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()


def list_listings(conn, view="inbox"):
    """view: inbox (not saved/rejected), saved, rejected, all. Only listings passing filters."""
    where = {"inbox": "status NOT IN ('SAVED','REJECTED','TAKEN')",
             "saved": "status NOT IN ('NEW','REJECTED')",
             "rejected": "status = 'REJECTED'",
             "all": "1=1"}[view]
    return conn.execute(
        f"SELECT * FROM listings WHERE passes_filters=1 AND {where} "
        "ORDER BY first_seen_at DESC, match_score DESC").fetchall()


def enqueue_notification(conn, listing_id, kind="new_listing", channel="telegram"):
    """Idempotent: the UNIQUE constraint means a listing is queued at most once per kind."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO notifications (listing_id, channel, kind, created_at) VALUES (?,?,?,?)",
        (listing_id, channel, kind, now()))
    conn.commit()
    return cur.rowcount > 0


def pending_notifications(conn, max_attempts, channel="telegram"):
    return conn.execute(
        "SELECT * FROM notifications WHERE channel=? AND status='pending' AND attempts < ? ORDER BY id",
        (channel, max_attempts)).fetchall()


def mark_notification(conn, notif_id, ok, error=None, max_attempts=5):
    if ok:
        conn.execute("UPDATE notifications SET status='sent', sent_at=?, attempts=attempts+1, last_error=NULL "
                     "WHERE id=?", (now(), notif_id))
    else:
        conn.execute("UPDATE notifications SET attempts=attempts+1, last_error=?, "
                     "status=CASE WHEN attempts+1 >= ? THEN 'failed' ELSE 'pending' END WHERE id=?",
                     (str(error)[:500], max_attempts, notif_id))
    conn.commit()


def start_scan(conn):
    cur = conn.execute("INSERT INTO scans (started_at) VALUES (?)", (now(),))
    conn.commit()
    return cur.lastrowid


def finish_scan(conn, scan_id, **stats):
    cols = ", ".join(f"{k}=?" for k in stats)
    conn.execute(f"UPDATE scans SET finished_at=?{', ' + cols if cols else ''} WHERE id=?",
                 [now(), *stats.values(), scan_id])
    conn.commit()


def last_scan(conn):
    return conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
