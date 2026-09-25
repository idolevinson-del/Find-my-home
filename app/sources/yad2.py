"""Yad2 adapter — the only file that knows Yad2's URLs and JSON shape.

Access approach taken from EladNa1/Apartment-Bot (see NOTICE.md): the
`gw.yad2.co.il` realestate feed, fetched with curl_cffi's Chrome TLS profile
because Yad2 sits behind Cloudflare. We deliberately add nothing beyond that:
no proxies, no fingerprint rotation, no captcha solving. If Yad2 blocks us, the
scan logs a clear error and the rest of the app keeps working on stored data.

Feed facts (from Apartment-Bot's GW_FEED_MIGRATION_PLAN.md, probed 2026-07):
  GET https://gw.yad2.co.il/realestate-feed/rent/feed?region=R&city=C&maxPrice=N&page=P
  - `region` is required; one city per request; neighborhoods are ignored server-side.
  - Allowed params: region, city, area, maxPrice, minPrice, minRooms, maxRooms,
    property, elevator, parking, page. Unknown params → HTTP 400.
  - Response: {"data": {"private": [...], "agency": [...], ..., "pagination": {"totalPages": N}}}
"""
import logging
import random
import time
from typing import Iterable, Optional

from app.models import Listing
from app.sources.base import BaseListingSource, SourceError

log = logging.getLogger("hunter")

try:
    from curl_cffi import requests as http
    HTTP_LIB = "curl_cffi"
except ImportError:  # still importable (tests, offline); live fetches will likely be blocked
    import requests as http
    HTTP_LIB = "requests"

YAD2_WWW = "https://www.yad2.co.il"
GW_FEED = "https://gw.yad2.co.il/realestate-feed/rent/feed"
# Single-ad endpoint used for the full description. NOT verified from this
# codebase's reference project — if it 404s, set yad2.fetch_details: false.
GW_ITEM = "https://gw.yad2.co.il/realestate-item/{token}"
GW_AUTOCOMPLETE = "https://gw.yad2.co.il/address-autocomplete/realestate/v2"
ITEM_URL = YAD2_WWW + "/item/{token}"

FEED_BUCKETS = ("private", "agency", "yad1", "platinum", "kingOfTheHar",
                "trio", "booster", "leadingBroker", "items", "feed_items")

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en;q=0.7",
    "Origin": YAD2_WWW,
    "Referer": YAD2_WWW + "/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# Hebrew property-type text → normalized type. Unknown text is kept as-is.
PROPERTY_TYPES = {
    "דירה": "apartment", "דירת גן": "garden_apartment", "גג/פנטהאוז": "penthouse",
    "פנטהאוז": "penthouse", "דירת גג": "rooftop", "דופלקס": "duplex", "טריפלקס": "triplex",
    "סטודיו/לופט": "studio", "יחידת דיור": "housing_unit", "בית פרטי/קוטג'": "house",
    "דו משפחתי": "semi_detached", "מרתף/פרטר": "basement",
}


def http_get_json(url, params=None, retries=2, timeout=30):
    kw = {"headers": HEADERS, "timeout": timeout, "params": params}
    if HTTP_LIB == "curl_cffi":
        kw["impersonate"] = "chrome124"
    last = None
    for attempt in range(retries + 1):
        try:
            r = http.get(url, **kw)
            if r.status_code != 200:
                raise SourceError(f"HTTP {r.status_code} from {url}")
            return r.json()
        except Exception as e:  # network error, block, bad JSON
            last = e
            if attempt < retries:
                time.sleep(2 + random.uniform(0, 2))
    raise SourceError(f"Yad2 request failed: {last}")


def _text(d, *keys):
    """Walk nested dicts; return the final value's `text` (or the value itself)."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    if isinstance(d, dict):
        d = d.get("text")
    return d or None


def _num(v, cast=float):
    try:
        return cast(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _has_tag(tags, *words):
    """True if a tag mentions the amenity; None otherwise (a missing tag ≠ 'no')."""
    return True if any(w in tags for w in words) else None


class Yad2Source(BaseListingSource):
    name = "yad2"

    @property
    def cfg(self):
        return self.settings.get("yad2", {})

    def feed_params(self, city, page):
        s = self.settings.get("search", {})
        params = {"region": self.cfg["region"], "city": city}
        if s.get("max_price"):
            params["maxPrice"] = int(s["max_price"])
        if s.get("min_price"):
            params["minPrice"] = int(s["min_price"])
        if s.get("min_rooms"):
            params["minRooms"] = s["min_rooms"]
        if s.get("max_rooms"):
            params["maxRooms"] = s["max_rooms"]
        if page > 1:
            params["page"] = page
        return params

    def search(self) -> Iterable[dict]:
        delay = float(self.cfg.get("delay_between_requests_sec", 2.5))
        max_pages = int(self.cfg.get("max_pages", 5))
        for city in self.cfg.get("cities", []):
            for page in range(1, max_pages + 1):
                if page > 1 or city != self.cfg["cities"][0]:
                    time.sleep(delay + random.uniform(0, 1))
                data = http_get_json(GW_FEED, self.feed_params(city, page))
                items = extract_items(data)
                log.debug(f"Yad2 city={city} page={page}: {len(items)} items")
                yield from items
                if not items or page >= total_pages(data):
                    break

    def normalize(self, raw: dict) -> Optional[Listing]:
        token = raw.get("token")
        if not token:
            return None
        addr = raw.get("address") or {}
        house = addr.get("house") or {}
        details = raw.get("additionalDetails") or {}
        meta = raw.get("metaData") or {}
        tags = " ".join(t.get("name", "") for t in raw.get("tags") or [] if isinstance(t, dict))

        street = _text(addr, "street")
        number = house.get("number")
        street_full = f"{street} {number}".strip() if street and number else street

        images = list(meta.get("images") or [])
        cover = meta.get("coverImage")
        if cover and cover not in images:
            images.insert(0, cover)

        prop_text = _text(details, "property")
        bucket = raw.get("_bucket")
        if bucket == "private":
            is_broker = False
        elif bucket in ("agency", "leadingBroker") or raw.get("adType") in ("agency", "business"):
            is_broker = True
        elif raw.get("adType") == "private":
            is_broker = False
        else:
            is_broker = None

        coords = addr.get("coords") or {}
        return Listing(
            source=self.name,
            source_id=str(token),
            url=ITEM_URL.format(token=token),
            title=" ".join(x for x in (prop_text, street_full) if x) or None,
            city=_text(addr, "city"),
            neighborhood=_text(addr, "neighborhood"),
            street=street_full,
            price=_num(raw.get("price"), int),
            rooms=_num(details.get("roomsCount")),
            size_sqm=_num(details.get("squareMeter")) or _num(meta.get("squareMeterBuild")),
            floor=_num(house.get("floor"), int),
            property_type=PROPERTY_TYPES.get(prop_text, prop_text),
            description=raw.get("description") or meta.get("description") or None,
            images=images,
            parking=_has_tag(tags, "חניה", "חנייה"),
            balcony=True if (_has_tag(tags, "מרפסת") or details.get("balcony")) else None,
            elevator=True if (_has_tag(tags, "מעלית") or details.get("elevator")) else None,
            furnished=_has_tag(tags, "מרוהטת", "ריהוט"),
            is_broker=is_broker,
            posted_at=raw.get("createdAt") or raw.get("date") or None,
            lat=_num(coords.get("lat")),
            lon=_num(coords.get("lon")),
        )

    def get_listing(self, source_id: str) -> Optional[dict]:
        data = http_get_json(GW_ITEM.format(token=source_id), retries=0)
        return data.get("data", data) if isinstance(data, dict) else None

    def enrich(self, listing: Listing) -> Listing:
        """Best-effort: add the description (and anything else missing) from the full ad."""
        if not self.cfg.get("fetch_details", True) or listing.description:
            return listing
        try:
            item = self.get_listing(listing.source_id) or {}
        except SourceError as e:
            log.warning(f"Yad2 details unavailable for {listing.source_id}: {e}")
            return listing
        meta = item.get("metaData") or {}
        listing.description = item.get("description") or meta.get("description") or listing.description
        extra = self.normalize({**item, "token": listing.source_id}) if item.get("address") else None
        if extra:
            for f in ("parking", "balcony", "elevator", "furnished", "size_sqm", "floor"):
                if getattr(listing, f) is None and getattr(extra, f) is not None:
                    setattr(listing, f, getattr(extra, f))
            if len(extra.images) > len(listing.images):
                listing.images = extra.images
        return listing


def extract_items(data):
    d = data.get("data") if isinstance(data, dict) else None
    d = d if isinstance(d, dict) else (data if isinstance(data, dict) else {})
    seen, out = set(), []
    for bucket in FEED_BUCKETS:
        for item in d.get(bucket) or []:
            if isinstance(item, dict) and item.get("token") and item["token"] not in seen:
                seen.add(item["token"])
                out.append({**item, "_bucket": bucket})
    return out


def total_pages(data):
    d = data.get("data") if isinstance(data, dict) else None
    try:
        return int((d or {}).get("pagination", {}).get("totalPages") or 1)
    except (TypeError, ValueError):
        return 1


def lookup_ids(text):
    """Ask Yad2's autocomplete for city/region/neighborhood ids (for config.yaml)."""
    return http_get_json(GW_AUTOCOMPLETE, {"text": text})
