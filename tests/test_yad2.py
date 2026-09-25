from app.sources.yad2 import Yad2Source, extract_items, total_pages


def test_extract_dedups_across_buckets(feed):
    items = extract_items(feed)
    tokens = [i["token"] for i in items]
    assert len(tokens) == len(set(tokens)) == 5
    assert total_pages(feed) == 1


def test_normalize_fields(feed, settings):
    src = Yad2Source(settings)
    by_id = {l.source_id: l for l in map(src.normalize, extract_items(feed))}
    f = by_id["florentin1"]
    assert (f.price, f.rooms, f.size_sqm, f.floor) == (10800, 4, 92, 3)
    assert f.neighborhood == "פלורנטין" and f.street == "הרצל 12"
    assert f.url == "https://www.yad2.co.il/item/florentin1"
    assert f.balcony is True and f.elevator is True
    assert f.images[0] == "https://img.example/1.jpg" and len(f.images) == 2
    assert f.property_type == "apartment"
    assert f.is_broker is False              # "private" bucket
    assert by_id["levontin1"].is_broker is True  # "agency" bucket


def test_missing_amenities_are_unknown_not_false(feed, settings):
    src = Yad2Source(settings)
    by_id = {l.source_id: l for l in map(src.normalize, extract_items(feed))}
    f = by_id["florentin1"]
    assert f.parking is None          # no parking tag → unknown, not False
    assert by_id["levontin1"].size_sqm is None
    assert by_id["levontin1"].parking is True


def test_feed_params_come_from_settings(settings):
    settings["search"]["max_price"] = 9000
    p = Yad2Source(settings).feed_params(5000, 2)
    assert p["maxPrice"] == 9000 and p["page"] == 2 and p["region"] == settings["yad2"]["region"]
