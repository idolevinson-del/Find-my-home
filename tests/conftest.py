import copy
import json
from pathlib import Path

import pytest
import yaml

from app import db
from app.models import Listing
from app.sources.base import BaseListingSource
from app.sources.yad2 import Yad2Source, extract_items

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
BASE_SETTINGS = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def settings():
    s = copy.deepcopy(BASE_SETTINGS)
    s["ai"]["enabled"] = False
    s["yad2"]["fetch_details"] = False
    s["yad2"]["delay_between_requests_sec"] = 0
    return s


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def feed():
    return json.loads((FIXTURES / "yad2_feed.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_secrets(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY", "SCAN_INTERVAL_MINUTES"):
        monkeypatch.delenv(k, raising=False)


class FixtureYad2(Yad2Source):
    """Yad2 adapter fed from a fixture instead of the network."""

    def __init__(self, settings, data):
        super().__init__(settings)
        self.data = data

    def search(self):
        return extract_items(self.data)


class FakeSession:
    """Stands in for `requests` — records posts, can be told to fail."""

    def __init__(self, fail=False):
        self.fail = fail
        self.posts = []

    def post(self, url, **kw):
        self.posts.append((url, kw))
        if self.fail:
            raise ConnectionError("telegram down")

        class R:
            status_code = 200
            text = "ok"
        return R()


def make_listing(**kw):
    base = dict(source="yad2", source_id="x1", url="https://www.yad2.co.il/item/x1",
                city="תל אביב יפו", neighborhood="פלורנטין", street="הרצל 1",
                price=11000, rooms=4, size_sqm=90, floor=2)
    base.update(kw)
    return Listing(**base)
