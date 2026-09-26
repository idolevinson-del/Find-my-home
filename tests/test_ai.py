import json

from app import ai, db, pipeline
from tests.conftest import FixtureYad2, make_listing

ANSWER = {"roommate_suitability": "high", "condition": "renovated", "has_balcony": True,
          "has_parking": None, "red_flags": ["ללא חיות"], "positive_points": [], "summary": "מתאימה לשותפים",
          "likely_noise_level": "made-up-value"}


class FakeGemini:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def post(self, url, **kw):
        self.calls += 1
        fail = self.fail

        class R:
            status_code = 500 if fail else 200
            text = "boom"

            def json(self_inner):
                return {"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER, ensure_ascii=False)}]}}]}
        return R()


def test_validate_rejects_off_schema():
    out = ai.validate(ANSWER)
    assert out["likely_noise_level"] == "unknown"
    assert out["has_parking"] is None and out["couples_only"] is None


def test_backlog_is_analyzed_when_ai_turns_on(conn, settings, feed, monkeypatch):
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)])       # AI off
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE ai_analysis IS NOT NULL").fetchone()[0] == 0
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    settings["ai"]["enabled"] = True
    g = FakeGemini()
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=g)
    rows = conn.execute("SELECT ai_analysis, score_breakdown FROM listings WHERE passes_filters=1").fetchall()
    assert len(rows) == 2 and all(r["ai_analysis"] for r in rows) and g.calls == 2
    assert "משופצת" in rows[0]["score_breakdown"]


def test_backlog_stops_on_failure(conn, settings, feed, monkeypatch):
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)])
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    settings["ai"]["enabled"] = True
    g = FakeGemini(fail=True)
    pipeline.run_scan(conn, settings, [FixtureYad2(settings, feed)], http_session=g)
    assert g.calls == 1


def test_busy_model_is_retried(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(ai, "RETRY_DELAY", 0)
    codes = iter([503, 503, 200])

    class Session:
        calls = 0

        def post(self, url, **kw):
            Session.calls += 1
            code = next(codes)

            class R:
                status_code = code
                text = "busy"

                def json(self_inner):
                    return {"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER)}]}}]}
            return R()

    out = ai.analyze(make_listing(description="x"), {"ai": {"enabled": True}}, session=Session())
    assert out and out["condition"] == "renovated" and Session.calls == 3
