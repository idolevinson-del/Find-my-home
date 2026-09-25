from app.filters import hard_filter
from tests.conftest import make_listing


def passes(settings, **kw):
    return hard_filter(make_listing(**kw), settings)[0]


def test_price_boundary(settings):
    assert passes(settings, price=12000)
    assert not passes(settings, price=12001)


def test_rooms(settings):
    assert passes(settings, rooms=4)
    assert not passes(settings, rooms=3)
    assert not passes(settings, rooms=5)


def test_ground_floor_rejected(settings):
    assert not passes(settings, floor=0)
    assert passes(settings, floor=1)


def test_unknown_floor_and_size_are_kept(settings):
    assert passes(settings, floor=None, size_sqm=None)


def test_small_size_rejected(settings):
    assert not passes(settings, size_sqm=79)
    assert passes(settings, size_sqm=80)


def test_area_modes(settings):
    assert not passes(settings, neighborhood="רמת אביב", street="איינשטיין 40")
    # a configured street name also counts as an area
    assert passes(settings, neighborhood="לב תל אביב", street="לבונטין 7")
    settings["search"]["area_mode"] = "prefer"
    assert passes(settings, neighborhood="רמת אביב", street="איינשטיין 40")


def test_filters_follow_settings(settings):
    settings["search"]["max_price"] = 9000
    assert not passes(settings, price=11000)


def test_reasons_are_reported(settings):
    ok, reasons = hard_filter(make_listing(price=13000, floor=0), settings)
    assert not ok and len(reasons) == 2
