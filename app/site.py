"""Build the static dashboard (GitHub Pages) from the database.

Same UI as the local dashboard; app.js switches to static mode when it finds
data.json next to it. Save/Reject on the static site are kept on the phone
(browser storage) and can be synced to the bot with a Telegram deep link.
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app import db
from app.config import secret

STATIC = Path(__file__).parent / "web" / "static"


def bot_username(session=None):
    if not secret("TELEGRAM_BOT_TOKEN"):
        return None
    try:
        import requests
        r = (session or requests).get(
            f"https://api.telegram.org/bot{secret('TELEGRAM_BOT_TOKEN')}/getMe", timeout=10)
        return r.json()["result"]["username"]
    except Exception:
        return None


def build(conn, settings, out_dir, repo=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "style.css", "app.js"):
        shutil.copy(STATIC / name, out / name)
    # Static hosting serves files relative to the page, not from /static/.
    html = (out / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/', 'href="').replace('src="/static/', 'src="')
    (out / "index.html").write_text(html, encoding="utf-8")

    rows = conn.execute("SELECT * FROM listings WHERE passes_filters=1 ORDER BY first_seen_at DESC").fetchall()
    scan = db.last_scan(conn)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "listings": [db.row_to_api(r) for r in rows],
        "settings": settings,
        "last_scan": dict(scan) if scan else None,
        "bot": bot_username(),
        "repo": repo,
    }
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return len(rows)
