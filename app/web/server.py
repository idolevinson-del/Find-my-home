"""Dashboard API + static UI (FastAPI)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, db, pipeline
from app.models import Status
from app.notify import telegram

STATIC = Path(__file__).parent / "static"
HIGH, GOOD = 90, 75


class StatusIn(BaseModel):
    status: str


def create_app(conn, scanner=None):
    app = FastAPI(title="Apartment Hunter TLV")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/listings")
    def listings(view: str = "inbox"):
        if view not in ("inbox", "saved", "rejected", "all"):
            raise HTTPException(400, "bad view")
        rows = [db.row_to_api(r) for r in db.list_listings(conn, view)]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        for r in rows:
            r["is_new"] = r["status"] == Status.NEW and r["first_seen_at"] >= cutoff
        rows.sort(key=lambda r: (not r["is_new"], -(r["match_score"] or 0)))
        return rows

    @app.get("/api/summary")
    def summary():
        inbox = [db.row_to_api(r) for r in db.list_listings(conn, "inbox")]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        new = [r for r in inbox if r["status"] == Status.NEW and r["first_seen_at"] >= cutoff]
        scan = db.last_scan(conn)
        return {
            "new": len(new),
            "excellent": sum(1 for r in inbox if (r["match_score"] or 0) >= HIGH),
            "good": sum(1 for r in inbox if GOOD <= (r["match_score"] or 0) < HIGH),
            "possible": sum(1 for r in inbox if (r["match_score"] or 0) < GOOD),
            "total": len(inbox),
            "saved": len(db.list_listings(conn, "saved")),
            "last_scan": dict(scan) if scan else None,
            "scanning": bool(scanner and scanner.running),
            "next_scan_at": scanner.next_scan_at if scanner else None,
            "telegram": telegram.configured(),
        }

    @app.post("/api/listings/{listing_id}/status")
    def set_status(listing_id: int, body: StatusIn):
        if body.status not in Status.ALL:
            raise HTTPException(400, "bad status")
        if not db.set_status(conn, listing_id, body.status):
            raise HTTPException(404, "not found")
        return {"ok": True}

    @app.post("/api/scan")
    def scan_now():
        if scanner is None:
            raise HTTPException(503, "scanner not running")
        scanner.scan_now()
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings():
        return config.load_settings()

    @app.put("/api/settings")
    def put_settings(patch: dict):
        merged = config.merge_settings(config.load_settings(), patch)
        config.save_settings(merged)
        pipeline.rescore_all(conn, merged)
        return merged

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
