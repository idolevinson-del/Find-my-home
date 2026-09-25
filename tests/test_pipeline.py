from app import db, pipeline
from app.sources.base import SourceError
from tests.conftest import FakeSession, FixtureYad2, make_listing


def test_same_listing_twice_is_stored_once(conn):
    assert db.upsert_listing(conn, make_listing())[1] == "new"
    assert db.upsert_listing(conn, make_listing())[1] == "unchanged"
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1


def test_price_change_updates_and_keeps_history(conn):
    lid, _ = db.upsert_listing(conn, make_listing(price=12000))
    assert db.upsert_listing(conn, make_listing(price=11500))[1] == "updated"
    assert db.get_listing(conn, lid)["price"] == 11500
    ch = conn.execute("SELECT field, old_value, new_value FROM listing_changes").fetchall()
    assert [tuple(r) for r in ch] == [("price", "12000", "11500")]


def test_unknown_does_not_overwrite_known(conn):
    lid, _ = db.upsert_listing(conn, make_listing(parking=True))
    db.upsert_listing(conn, make_listing(parking=None))
    assert db.get_listing(conn, lid)["parking"] == 1


def test_unknown_parking_roundtrips_as_none(conn):
    lid, _ = db.upsert_listing(conn, make_listing(parking=None, balcony=False))
    l = db.row_to_listing(db.get_listing(conn, lid))
    assert l.parking is None and l.balcony is False


def test_scan_filters_and_notifies_once(conn, settings, feed, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    settings["notifications"]["min_score"] = 0
    tg = FakeSession()

    s1 = pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    assert s1["fetched"] == 5 and s1["new"] == 5
    passing = {r["source_id"] for r in conn.execute("SELECT source_id FROM listings WHERE passes_filters=1")}
    assert passing == {"florentin1", "levontin1"}   # ground floor, 12001 and Ramat Aviv rejected
    assert s1["notified"] == 2 and len(tg.posts) == 2

    # Second scan with one new listing: only that one is announced.
    feed["data"]["private"].append({**feed["data"]["private"][0], "token": "florentin2", "price": 11000})
    s2 = pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    assert s2["new"] == 1 and s2["notified"] == 1 and len(tg.posts) == 3
    assert "florentin2" in tg.posts[-1][1]["json"]["reply_markup"]["inline_keyboard"][0][0]["url"]

    # Third scan, nothing new: no messages.
    s3 = pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    assert s3["new"] == 0 and s3["notified"] == 0 and len(tg.posts) == 3


def test_telegram_failure_keeps_listing_and_retries(conn, settings, feed, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    settings["notifications"]["min_score"] = 0

    down = FakeSession(fail=True)
    s1 = pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=down)
    assert s1["notified"] == 0
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE passes_filters=1").fetchone()[0] == 2
    rows = conn.execute("SELECT status, attempts FROM notifications").fetchall()
    assert [tuple(r) for r in rows] == [("pending", 1), ("pending", 1)]

    up = FakeSession()
    s2 = pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=up)
    assert s2["new"] == 0 and s2["notified"] == 2 and len(up.posts) == 2
    assert {r[0] for r in conn.execute("SELECT status FROM notifications")} == {"sent"}


def test_source_failure_is_logged_not_crash(conn, settings):
    class Broken(FixtureYad2):
        def search(self):
            raise SourceError("HTTP 403")
    stats = pipeline.run_scan(conn, settings, [Broken(settings, {})])
    assert stats["error"] and "403" in stats["error"]
    assert db.last_scan(conn)["error"]


def test_rejected_listing_hidden_from_inbox(conn, settings, feed):
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)])
    lid = conn.execute("SELECT id FROM listings WHERE source_id='florentin1'").fetchone()[0]
    db.set_status(conn, lid, "REJECTED")
    assert lid not in [r["id"] for r in db.list_listings(conn, "inbox")]
    assert lid in [r["id"] for r in db.list_listings(conn, "rejected")]


def test_settings_change_rescores(conn, settings, feed):
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)])
    settings["search"]["area_mode"] = "prefer"
    pipeline.rescore_all(conn, settings)
    passing = {r["source_id"] for r in conn.execute("SELECT source_id FROM listings WHERE passes_filters=1")}
    assert "ramataviv1" in passing
