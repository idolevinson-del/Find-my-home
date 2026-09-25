import json

import pytest

from app import db, pipeline, site
from app.notify import bot
from tests.conftest import FixtureYad2, make_listing


class FakeTelegram:
    """Fake Bot API: queued updates for getUpdates, records everything else."""

    def __init__(self, updates=()):
        self.updates = list(updates)
        self.calls = []

    def post(self, url, json=None, **kw):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json))
        result = [u for u in self.updates if u["update_id"] >= json.get("offset", 0)] \
            if method == "getUpdates" else {"message_id": 1}

        class R:
            status_code = 200
            text = "ok"

            def json(self_inner):
                return {"ok": True, "result": result}
        return R()

    def sent(self, method):
        return [p for m, p in self.calls if m == method]


def msg(update_id, text, chat=6633022823):
    return {"update_id": update_id, "message": {"chat": {"id": chat}, "text": text}}


@pytest.fixture(autouse=True)
def tg_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "6633022823")


def test_budget_command_changes_settings(conn, settings):
    tg = FakeTelegram([msg(1, "תקציב 13,000")])
    assert bot.process_updates(conn, settings, session=tg)
    assert bot.effective_settings(conn, settings)["search"]["max_price"] == 13000
    assert "13,000" in tg.sent("sendMessage")[0]["text"]
    # offset stored → the same update is not handled twice
    assert not bot.process_updates(conn, settings, session=tg)
    assert len(tg.sent("sendMessage")) == 1


def test_rooms_range_and_areas(conn, settings):
    tg = FakeTelegram([msg(1, "חדרים 3.5-5"), msg(2, "הוסף אזור יפו"), msg(3, "הסר אזור פלורנטין")])
    bot.process_updates(conn, settings, session=tg)
    s = bot.effective_settings(conn, settings)
    assert (s["search"]["min_rooms"], s["search"]["max_rooms"]) == (3.5, 5)
    places = [p for g in s["areas"] for p in g["places"]]
    assert "יפו" in places and "פלורנטין" not in places
    assert settings["areas"][0]["places"][0] == "פלורנטין"   # config itself untouched


def test_strangers_are_ignored(conn, settings):
    tg = FakeTelegram([msg(1, "תקציב 1", chat=999)])
    assert not bot.process_updates(conn, settings, session=tg)
    assert bot.effective_settings(conn, settings)["search"]["max_price"] == 12000
    assert tg.sent("sendMessage") == []


def test_unknown_command_gets_help(conn, settings):
    tg = FakeTelegram([msg(1, "מה קורה")])
    bot.process_updates(conn, settings, session=tg)
    assert "לא הבנתי" in tg.sent("sendMessage")[0]["text"]


def test_save_and_reject_buttons(conn, settings):
    lid, _ = db.upsert_listing(conn, make_listing())
    tap = {"update_id": 5, "callback_query": {"id": "cb", "data": f"s:{lid}", "from": {"id": 6633022823},
                                              "message": {"message_id": 9, "chat": {"id": 6633022823}}}}
    tg = FakeTelegram([tap])
    bot.process_updates(conn, settings, session=tg)
    assert db.get_listing(conn, lid)["status"] == "SAVED"
    kb = tg.sent("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"]
    assert "נשמרה" in kb[1][0]["text"]

    tg = FakeTelegram([{**tap, "update_id": 6, "callback_query": {**tap["callback_query"], "data": f"r:{lid}"}}])
    bot.process_updates(conn, settings, session=tg)
    assert db.get_listing(conn, lid)["status"] == "REJECTED"


def test_alert_has_buttons(conn, settings, feed):
    tg = FakeTelegram()
    settings["notifications"]["min_score"] = 0
    pipeline.run_cycle(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    kb = tg.sent("sendMessage")[0]["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["url"].startswith("https://www.yad2.co.il/item/")
    assert [b["callback_data"][:2] for b in kb[1]] == ["s:", "r:"]


def test_price_drop_alert(conn, settings, feed):
    tg = FakeTelegram()
    settings["notifications"]["min_score"] = 0
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    before = len(tg.sent("sendMessage"))
    feed["data"]["private"][0]["price"] = 10000          # florentin1: 10,800 → 10,000
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    texts = [p["text"] for p in tg.sent("sendMessage")[before:]]
    assert len(texts) == 1 and "המחיר ירד" in texts[0] and "10,800" in texts[0]


def test_no_price_drop_alert_for_rejected(conn, settings, feed):
    tg = FakeTelegram()
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    lid = conn.execute("SELECT id FROM listings WHERE source_id='florentin1'").fetchone()[0]
    db.set_status(conn, lid, "REJECTED")
    before = len(tg.sent("sendMessage"))
    feed["data"]["private"][0]["price"] = 10000
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=tg)
    assert len(tg.sent("sendMessage")) == before


def test_site_build(conn, settings, feed, tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)])
    n = site.build(conn, settings, tmp_path / "site", repo="me/repo")
    data = json.loads((tmp_path / "site" / "data.json").read_text(encoding="utf-8"))
    assert n == 2 and len(data["listings"]) == 2 and data["repo"] == "me/repo"
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert 'src="app.js"' in html and "/static/" not in html


def test_multi_line_natural_commands(conn, settings):
    tg = FakeTelegram([msg(1, "הוסף אזור רחוב אילת בתל אביב\nאפשר קרקע")])
    assert bot.process_updates(conn, settings, session=tg)
    s = bot.effective_settings(conn, settings)
    assert "אילת" in [p for g in s["areas"] for p in g["places"]]
    assert s["search"]["exclude_ground_floor"] is False
    reply = tg.sent("sendMessage")[0]["text"]
    assert "אילת" in reply and "קרקע" in reply and "לא הבנתי" not in reply
    tg = FakeTelegram([msg(2, "בלי קרקע")])
    bot.process_updates(conn, settings, session=tg)
    assert bot.effective_settings(conn, settings)["search"]["exclude_ground_floor"] is True
