"""Telegram notifications, sent from the DB outbox.

A listing is queued once (UNIQUE in `notifications`). Sending marks it sent;
a failure leaves it pending, so the next scan retries it — the listing itself is
already safe in the DB either way.
"""
import html
import json
import logging

import requests

from app import db
from app.config import secret

log = logging.getLogger("hunter")

API = "https://api.telegram.org/bot{token}/sendMessage"
MARK = {"yes": "✓", "no": "✗", "unknown": "?"}


def configured():
    return bool(secret("TELEGRAM_BOT_TOKEN") and secret("TELEGRAM_CHAT_ID"))


def format_message(row):
    """Build the Hebrew alert text + inline 'open ad' button for a listing row."""
    e = html.escape
    score = row["match_score"]
    fire = "🔥" if (score or 0) >= 90 else "🏠"
    lines = [f"{fire} <b>דירה חדשה שמתאימה לך</b>", f"<b>MATCH: {score}%</b>", ""]
    place = ", ".join(x for x in (row["neighborhood"], row["street"]) if x)
    if place:
        lines.append(f"📍 {e(place)}")
    if row["price"] is not None:
        lines.append(f"💰 ₪{row['price']:,}")
    if row["rooms"] is not None:
        lines.append(f"🛏 {row['rooms']:g} חדרים")
    if row["size_sqm"] is not None:
        lines.append(f'📐 {row["size_sqm"]:g} מ"ר')
    if row["floor"] is not None:
        lines.append(f"🏢 קומה {row['floor']}")
    breakdown = json.loads(row["score_breakdown"] or "[]")
    if breakdown:
        lines.append("")
        for item in breakdown:
            if item["key"] in ("price", "rooms", "size", "floor") and item["state"] == "yes":
                continue  # already shown above
            icon = {"yes": "✓", "no": "⚠️", "unknown": "?"}[item["state"]]
            lines.append(f"{icon} {e(item['label'])}")
    ai = json.loads(row["ai_analysis"]) if row["ai_analysis"] else None
    if ai and ai.get("summary"):
        lines += ["", f"🤖 {e(ai['summary'])}"]
    # Plain link too, not just the button — the phone number is on the ad page.
    lines += ["", f'🔗 <a href="{e(row["url"])}">למודעה ביד2 (טלפון ופרטים)</a>', e(row["url"])]
    keyboard = {"inline_keyboard": [[{"text": "פתח מודעה", "url": row["url"]}]]}
    return "\n".join(lines), keyboard


def send(text, keyboard, session=requests):
    token, chat = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    r = session.post(API.format(token=token), timeout=15, json={
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": False, "reply_markup": keyboard})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram HTTP {r.status_code}: {r.text[:200]}")


def flush_outbox(conn, settings, session=requests):
    """Send every pending Telegram notification. Returns number sent."""
    ncfg = settings.get("notifications", {})
    max_attempts = int(ncfg.get("max_attempts", 5))
    pending = db.pending_notifications(conn, max_attempts)
    if not pending:
        return 0
    if not ncfg.get("telegram_enabled", True) or not configured():
        log.info(f"Telegram not configured — {len(pending)} notification(s) waiting")
        return 0
    sent = 0
    for n in pending:
        row = db.get_listing(conn, n["listing_id"])
        if row is None or row["status"] == "REJECTED":
            db.mark_notification(conn, n["id"], True)  # nothing to send; close it
            continue
        try:
            send(*format_message(row), session=session)
            db.mark_notification(conn, n["id"], True)
            sent += 1
        except Exception as ex:
            db.mark_notification(conn, n["id"], False, ex, max_attempts)
            log.error(f"Telegram send failed for listing {row['id']} (will retry): {ex}")
    if sent:
        log.info(f"Telegram: {sent} notification(s) sent")
    return sent
