from app.scoring import score_listing
from tests.conftest import make_listing


def test_same_input_same_score(settings):
    a = score_listing(make_listing(balcony=True), settings)
    b = score_listing(make_listing(balcony=True), settings)
    assert a == b


def test_breakdown_is_explained(settings):
    score, items = score_listing(make_listing(balcony=True, parking=False), settings)
    assert 0 <= score <= 100
    by_key = {i["key"]: i for i in items}
    assert by_key["balcony"]["state"] == "yes"
    assert by_key["parking"]["state"] == "no"
    assert by_key["area"]["state"] == "yes"


def test_unknown_parking_is_not_no_parking(settings):
    unknown, items_u = score_listing(make_listing(parking=None), settings)
    no, items_n = score_listing(make_listing(parking=False), settings)
    assert {i["key"]: i for i in items_u}["parking"]["state"] == "unknown"
    assert {i["key"]: i for i in items_n}["parking"]["state"] == "no"
    assert unknown > no


def test_better_listing_scores_higher(settings):
    good, _ = score_listing(make_listing(balcony=True, parking=True, is_broker=False), settings)
    meh, _ = score_listing(make_listing(balcony=False, parking=False, is_broker=True), settings)
    assert good > meh


def test_ai_fills_unknowns(settings):
    base, _ = score_listing(make_listing(), settings)
    with_ai, items = score_listing(make_listing(), settings,
                                   {"roommate_suitability": "high", "condition": "renovated", "has_balcony": True})
    assert with_ai > base
    assert {i["key"]: i for i in items}["balcony"]["label"].endswith("(לפי התיאור)")


def test_weights_are_configurable(settings):
    settings["scoring"] = {"price": 1}
    score, items = score_listing(make_listing(), settings)
    assert score == 100 and len(items) == 1
