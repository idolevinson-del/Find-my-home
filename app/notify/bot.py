"""Two-way Telegram: button taps (save / reject) and text commands that change settings.

The scanner runs in GitHub Actions, not as an always-on server, so updates are
read at the start of each scan (getUpdates with a stored offset). A tap or a
command therefore takes effect on the next scan, i.e. within minutes.

Only messages from TELEGRAM_CHAT_ID are obeyed; everyone else is ignored.
Settings changed here are stored in the DB (kv 'settings_overrides') and
layered over config.yaml, so nothing has to be committed to the repo.
"""
import copy
import logging
import re

import requests

from app import db
from app.config import merge_settings, secret
from app.models import Status

log = logging.getLogger("hunter")

API = "https://api.telegram.org/bot{token}/{method}"
OVERRIDES = "settings_overrides"
BOT_AREA_GROUP = "נוספו בטלגרם"

HELP = """<b>פקודות</b> (אפשר בעברית, בלי סלאש):
• <b>הגדרות</b> — מה אני מחפש עכשיו
• <b>שמורות</b> — הדירות ששמרת
• <b>תקציב 13000</b> — מחיר מקסימלי
• <b>חדרים 4</b> או <b>חדרים 3.5-5</b>
• <b>גודל 80</b> — מינימום מ"ר
• <b>בלי קרקע</b> / <b>אפשר קרקע</b> — קומת קרקע
• <b>הוסף אזור אילת</b> / <b>הסר אזור אילת</b> — שכונה או רחוב
אפשר כמה פקודות בהודעה אחת, כל אחת בשורה נפרדת.
• <b>אזורים</b> — רשימת האזורים
• <b>שותפים 3</b> · <b>מרפסת חשוב</b> / <b>חניה לא משנה</b>
• <b>ציון 70</b> — ציון מינימלי להתראה
• <b>עזרה</b>
השינויים נכנסים לתוקף בסריקה הבאה (תוך כמה דקות)."""


def call(method, session=requests, **params):
    r = session.post(API.format(token=secret("TELEGRAM_BOT_TOKEN"), method=method), json=params, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {method} HTTP {r.status_code}: {getattr(r, 'text', '')[:200]}")
    return r.json().get("result") if hasattr(r, "json") else None


def status_keyboard(url, listing_id, status=None):
    rows = [[{"text": "פתח מודעה", "url": url}]]
    if status == Status.SAVED:
        rows.append([{"text": "❤️ נשמרה — בטל", "callback_data": f"u:{listing_id}"}])
    elif status == Status.REJECTED:
        rows.append([{"text": "❌ נדחתה — בטל", "callback_data": f"u:{listing_id}"}])
    else:
        rows.append([{"text": "❤️ שמור", "callback_data": f"s:{listing_id}"},
                     {"text": "❌ לא מתאים", "callback_data": f"r:{listing_id}"}])
    return {"inline_keyboard": rows}


def effective_settings(conn, base):
    return merge_settings(base, db.kv_get(conn, OVERRIDES, {}))


PLACE_PREFIXES = ("רחוב ", "רח' ", "שכונת ", "שכונה ", "אזור ")
PLACE_SUFFIXES = (" בתל אביב יפו", " בתל אביב", " תל אביב", " בת\"א", " בתא")


def clean_place(text):
    """'רחוב אילת בתל אביב' → 'אילת' (Yad2 writes just the street/neighborhood name)."""
    p = text.strip().strip(".,")
    for pre in PLACE_PREFIXES:
        if p.startswith(pre):
            p = p[len(pre):]
    for suf in PLACE_SUFFIXES:
        if p.endswith(suf):
            p = p[: -len(suf)]
    return p.strip()


def _num(text):
    return float(text.replace(",", "").replace("₪", "").strip())


def apply_command(conn, base, text):
    """Parse one text command. Returns (reply_html, settings_changed)."""
    t = text.strip().lstrip("/").strip()
    low = t.lower()
    settings = effective_settings(conn, base)
    over = db.kv_get(conn, OVERRIDES, {})

    def patch(section, key, value):
        over.setdefault(section, {})[key] = value

    def save():
        db.kv_set(conn, OVERRIDES, over)

    try:
        if low in ("start", "help", "עזרה") or low.startswith("start "):
            return HELP, False
        if low in ("settings", "הגדרות"):
            return describe(settings), False
        if low in ("saved", "שמורות"):
            rows = db.list_listings(conn, "saved")
            if not rows:
                return "עוד לא שמרת דירות.", False
            return "<b>❤️ שמורות</b>\n" + "\n".join(
                f'• <a href="{r["url"]}">{r["neighborhood"] or r["street"] or "דירה"}</a> — ₪{r["price"]:,}'
                for r in rows[:30]), False
        if low in ("areas", "אזורים"):
            return "<b>אזורים</b>\n" + "\n".join(
                f"• {g['name']}: {', '.join(g.get('places') or []) or '—'}" for g in settings.get("areas") or []), False

        m = re.match(r"^(?:budget|תקציב)\s+([\d,₪ ]+)$", low)
        if m:
            patch("search", "max_price", int(_num(m.group(1))))
            save()
            return f"✓ תקציב מקסימלי: ₪{int(_num(m.group(1))):,}", True
        m = re.match(r"^(?:rooms|חדרים)\s+([\d.]+)(?:\s*-\s*([\d.]+))?$", low)
        if m:
            lo = float(m.group(1)); hi = float(m.group(2) or m.group(1))
            patch("search", "min_rooms", lo); patch("search", "max_rooms", hi)
            save()
            return f"✓ חדרים: {lo:g}" + (f"–{hi:g}" if hi != lo else ""), True
        m = re.match(r"^(?:size|גודל)\s+([\d,]+)$", low)
        if m:
            patch("search", "min_size", int(_num(m.group(1))))
            save()
            return f'✓ מינימום {int(_num(m.group(1)))} מ"ר', True
        m = re.match(r"^(?:ground|קרקע)\s+(\S+)$", low) or \
            re.match(r"^(אפשר|מותר|כולל|עם|בלי|ללא|לא)\s+(?:קומת\s+)?קרקע$", low)
        if m:
            allow = m.group(1) in ("כן", "on", "yes", "אפשר", "מותר", "כולל", "עם")
            patch("search", "exclude_ground_floor", not allow)
            save()
            return "✓ קומת קרקע " + ("מותרת" if allow else "לא מוצגת"), True
        m = re.match(r"^(?:minscore|ציון)\s+(\d+)$", low)
        if m:
            patch("notifications", "min_score", int(m.group(1)))
            save()
            return f"✓ התראה רק מציון {m.group(1)}", True
        m = re.match(r"^(?:area_add|הוסף אזור)\s+(.+)$", t)
        if m:
            place = clean_place(m.group(1))
            areas = copy.deepcopy(settings.get("areas") or [])
            if any(place in (g.get("places") or []) for g in areas):
                return f"{place} כבר ברשימה", False
            group = next((g for g in areas if g["name"] == BOT_AREA_GROUP), None)
            if group is None:
                group = {"name": BOT_AREA_GROUP, "places": []}
                areas.append(group)
            group["places"].append(place)
            over["areas"] = areas
            save()
            return f"✓ נוסף אזור: {place}", True
        m = re.match(r"^(?:area_remove|הסר אזור)\s+(.+)$", t)
        if m:
            place = clean_place(m.group(1))
            areas = copy.deepcopy(settings.get("areas") or [])
            found = False
            for g in areas:
                if place in (g.get("places") or []):
                    g["places"].remove(place)
                    found = True
            if not found:
                return f"לא מצאתי את {place} ברשימת האזורים", False
            over["areas"] = [g for g in areas if g.get("places") or g["name"] != BOT_AREA_GROUP]
            save()
            return f"✓ הוסר אזור: {place}", True
        # Sent by the site's search wizard: replaces the whole area list.
        m = re.match(r"^(?:set_areas|קבע אזורים)\s*:?\s*(.+)$", t)
        if m:
            places = [p for p in (clean_place(x) for x in re.split(r"[,،]", m.group(1))) if p]
            over["areas"] = [{"name": "האזורים שלי", "places": places}]
            save()
            return f"✓ אזורים: {', '.join(places)}", True
        m = re.match(r"^(?:roommates|שותפים)\s+(\d+)$", low)
        if m:
            patch("preferences", "roommates", int(m.group(1)))
            save()
            return f"✓ {m.group(1)} שותפים", True
        m = re.match(r"^(מרפסת|חניה|חנייה|מעלית)\s+(חשוב|חשובה|כן|לא משנה|לא)$", t)
        if m:
            key = {"מרפסת": "balcony", "חניה": "parking", "חנייה": "parking", "מעלית": "elevator"}[m.group(1)]
            preferred = m.group(2) in ("חשוב", "חשובה", "כן")
            patch("preferences", key, "preferred" if preferred else "ignore")
            save()
            return f"✓ {m.group(1)}: {'חשוב' if preferred else 'לא משנה'}", True
    except ValueError:
        return "לא הבנתי את המספר 🤔\n\n" + HELP, False
    return "לא הבנתי 🤔\n\n" + HELP, False


def describe(s):
    se, p, n = s["search"], s.get("preferences", {}), s.get("notifications", {})
    rooms = f"{se['min_rooms']:g}" if se.get("min_rooms") == se.get("max_rooms") else f"{se.get('min_rooms') or 0:g}–{se.get('max_rooms') or '∞'}"
    return "\n".join([
        "<b>🔎 מה אני מחפש</b>",
        f"• {se.get('city')}",
        f"• {rooms} חדרים",
        f"• מחיר: מ-₪{se.get('min_price') or 0:,} עד ₪{se.get('max_price'):,}",
        f"• מינימום {se.get('min_size') or 0} מ\"ר",
        f"• קומת קרקע: {'לא' if se.get('exclude_ground_floor') else 'כן'}",
        f"• אזורים: {', '.join(x for g in s.get('areas') or [] for x in g.get('places') or [])}",
        f"• שותפים: {p.get('roommates')}",
        f"• התראה מציון {n.get('min_score', 0)}",
    ])


def set_listing_status(conn, listing_id, status):
    row = db.get_listing(conn, listing_id)
    if row is None:
        return None
    db.set_status(conn, listing_id, status)
    return row


def process_updates(conn, base, session=requests):
    """Handle everything the user sent since the last scan. Returns True if settings changed."""
    if not (secret("TELEGRAM_BOT_TOKEN") and secret("TELEGRAM_CHAT_ID")):
        return False
    chat_id = str(secret("TELEGRAM_CHAT_ID"))
    offset = db.kv_get(conn, "telegram_offset", 0)
    try:
        updates = call("getUpdates", session, offset=offset, timeout=0,
                       allowed_updates=["message", "callback_query"]) or []
    except Exception as e:
        log.warning(f"Telegram getUpdates failed: {e}")
        return False
    changed = False
    for u in updates:
        db.kv_set(conn, "telegram_offset", u["update_id"] + 1)
        try:
            if "callback_query" in u:
                changed |= _handle_callback(conn, u["callback_query"], chat_id, session)
            elif "message" in u:
                msg = u["message"]
                if str(msg.get("chat", {}).get("id")) != chat_id or not msg.get("text"):
                    continue
                text = msg["text"].strip()
                m = re.match(r"^/start\s+(save|reject|undo)_(\d+)$", text)
                if m:
                    status = {"save": Status.SAVED, "reject": Status.REJECTED, "undo": Status.NEW}[m.group(1)]
                    row = set_listing_status(conn, int(m.group(2)), status)
                    reply = "✓ עודכן" if row else "לא מצאתי את הדירה"
                else:
                    replies = []
                    for line in [l for l in text.splitlines() if l.strip()]:
                        r_, did = apply_command(conn, base, line)
                        replies.append(r_)
                        changed |= did
                    reply = "\n".join(replies)
                call("sendMessage", session, chat_id=chat_id, text=reply, parse_mode="HTML",
                     disable_web_page_preview=True)
        except Exception as e:
            log.warning(f"Telegram update {u.get('update_id')} failed: {e}")
    if updates:
        log.info(f"Telegram: handled {len(updates)} message(s)/tap(s)")
    return changed


def _handle_callback(conn, cq, chat_id, session):
    if str(cq.get("from", {}).get("id")) != chat_id and str(cq.get("message", {}).get("chat", {}).get("id")) != chat_id:
        return False
    action, _, lid = (cq.get("data") or "").partition(":")
    status = {"s": Status.SAVED, "r": Status.REJECTED, "u": Status.NEW}.get(action)
    if status is None or not lid.isdigit():
        return False
    row = set_listing_status(conn, int(lid), status)
    try:  # callback answers expire; the tap may be many minutes old
        call("answerCallbackQuery", session, callback_query_id=cq["id"])
    except Exception:
        pass
    msg = cq.get("message") or {}
    if row is not None and msg.get("message_id"):
        try:
            call("editMessageReplyMarkup", session, chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                 reply_markup=status_keyboard(row["url"], row["id"], status))
        except Exception as e:
            log.warning(f"Telegram edit failed: {e}")
    return False
