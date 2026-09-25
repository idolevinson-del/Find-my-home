"""Command-line helpers.

    python -m app.cli scan           one scan now, print the log
    python -m app.cli check-yad2     can we reach Yad2? prints a parsed sample
    python -m app.cli lookup "תל אביב"   find Yad2 region/city ids for config.yaml
    python -m app.cli test-telegram  send a test message to your phone
"""
import json
import sys

from app import config, db, pipeline
from app.logging_setup import setup
from app.notify import telegram
from app.sources.base import SourceError
from app.sources.yad2 import GW_FEED, Yad2Source, extract_items, http_get_json, lookup_ids


def main(argv):
    config.load_dotenv()
    log = setup()
    cmd = argv[1] if len(argv) > 1 else "help"
    settings = config.load_settings()

    if cmd == "scan":
        conn = db.connect()
        stats = pipeline.run_scan(conn, settings)
        conn.close()  # checkpoints the WAL so the .db file alone holds everything
        log.info(f"Result: {stats}")
        return 1 if stats["error"] and not stats["fetched"] else 0
    elif cmd == "check-yad2":
        src = Yad2Source(settings)
        city = settings["yad2"]["cities"][0]
        try:
            data = http_get_json(GW_FEED, src.feed_params(city, 1))
        except SourceError as e:
            log.error(f"FAILED: {e}")
            return 1
        items = extract_items(data)
        log.info(f"OK: {len(items)} listings on page 1")
        if items:
            print(json.dumps(src.normalize(items[0]).to_dict(), ensure_ascii=False, indent=2))
    elif cmd == "lookup":
        print(json.dumps(lookup_ids(" ".join(argv[2:])), ensure_ascii=False, indent=2))
    elif cmd == "test-telegram":
        telegram.send("✅ Apartment Hunter מחובר לטלגרם", {"inline_keyboard": []})
        log.info("Sent")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
