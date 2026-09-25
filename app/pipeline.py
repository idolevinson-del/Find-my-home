"""One scan: fetch → normalize → store/dedup → hard filters → (AI) → score → notify."""
import json
import logging
import random
import time

from app import ai, db
from app.filters import hard_filter, match_area
from app.notify import telegram
from app.scoring import score_listing
from app.sources.base import SourceError
from app.sources.yad2 import Yad2Source

log = logging.getLogger("hunter")

HIGH_MATCH = 90


def get_sources(settings):
    """All active sources. Add Madlan/WinWin/... here later."""
    return [Yad2Source(settings)]


def evaluate(conn, listing_id, settings):
    """(Re)compute filters + score for one stored listing. Returns (passes, score)."""
    row = db.get_listing(conn, listing_id)
    listing = db.row_to_listing(row)
    analysis = json.loads(row["ai_analysis"]) if row["ai_analysis"] else None
    passes, reasons = hard_filter(listing, settings)
    group, _ = match_area(listing, settings)
    score, breakdown = score_listing(listing, settings, analysis) if passes else (None, None)
    db.set_evaluation(conn, listing_id, passes, reasons, group, score, breakdown)
    return passes, score


def rescore_all(conn, settings):
    """Re-apply filters/score to every stored listing (after settings change)."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM listings")]
    for i in ids:
        evaluate(conn, i, settings)
    return len(ids)


def run_scan(conn, settings, sources=None, http_session=None):
    stats = {"fetched": 0, "passed": 0, "new": 0, "updated": 0, "notified": 0, "error": None}
    scan_id = db.start_scan(conn)
    log.info("Starting scan")
    new_matches = []  # (listing_id, source)

    for source in sources if sources is not None else get_sources(settings):
        try:
            raws = list(source.search())
        except SourceError as e:
            log.error(f"{source.name} request failed: {e}")
            stats["error"] = f"{source.name}: {e}"
            continue
        except Exception as e:  # never a silent crash
            log.exception(f"{source.name} scan crashed: {e}")
            stats["error"] = f"{source.name}: {e}"
            continue
        log.info(f"Fetched {len(raws)} {source.name} listings")
        stats["fetched"] += len(raws)

        for raw in raws:
            listing = source.normalize(raw)
            if listing is None:
                continue
            listing_id, outcome = db.upsert_listing(conn, listing, raw)
            passes, _ = evaluate(conn, listing_id, settings)
            stats["passed"] += int(passes)
            if outcome == "updated":
                stats["updated"] += 1
            if outcome == "new":
                stats["new"] += 1
                if passes:
                    new_matches.append((listing_id, source))

    log.info(f"{stats['passed']} passed hard filters")
    log.info(f"{len(new_matches)} new listings")

    # Extra work only for new listings that passed the filters: full ad text, then AI.
    ai_budget = int(settings.get("ai", {}).get("max_per_scan", 10)) if ai.enabled(settings) else 0
    delay = float(settings.get("yad2", {}).get("delay_between_requests_sec", 2.5))
    for i, (listing_id, source) in enumerate(new_matches):
        listing = db.row_to_listing(db.get_listing(conn, listing_id))
        if not listing.description:
            if i:
                time.sleep(delay + random.uniform(0, 1))
            enriched = source.enrich(listing)
            db.upsert_listing(conn, enriched)
            listing = enriched
        if ai_budget > 0:
            analysis = ai.analyze(listing, settings, **({"session": http_session} if http_session else {}))
            if analysis:
                db.set_ai_analysis(conn, listing_id, analysis)
            ai_budget -= 1
        evaluate(conn, listing_id, settings)

    # Queue notifications for the best new matches (capped so we never flood the phone).
    ncfg = settings.get("notifications", {})
    min_score = int(ncfg.get("min_score", 0))
    scored = [(db.get_listing(conn, i)["match_score"] or 0, i) for i, _ in new_matches]
    eligible = sorted((x for x in scored if x[0] >= min_score), reverse=True)
    high = sum(1 for s, _ in eligible if s >= HIGH_MATCH)
    if high:
        log.info(f"{high} high-match listing(s)")
    for _, listing_id in eligible[: int(ncfg.get("max_per_scan", 10))]:
        db.enqueue_notification(conn, listing_id)

    # Send everything pending — including earlier sends that failed.
    stats["notified"] = telegram.flush_outbox(conn, settings, **({"session": http_session} if http_session else {}))
    db.finish_scan(conn, scan_id, **stats)
    log.info("Scan complete" + (f" (with errors: {stats['error']})" if stats["error"] else ""))
    return stats
