"""Deterministic hard filters and area matching. No AI here.

Unknown values pass (the listing is kept and the score shows the unknown);
only a known value that breaks a rule rejects the listing.
"""
from app.models import Listing


def _norm(s):
    return (s or "").replace("-", " ").replace("־", " ").strip().lower()


def match_area(listing: Listing, settings):
    """Return (group_name, place) of the first configured place found in the
    listing's neighborhood/street text, or (None, None)."""
    text = _norm(f"{listing.neighborhood or ''} {listing.street or ''} {listing.title or ''}")
    for group in settings.get("areas") or []:
        for place in group.get("places") or []:
            if place and _norm(place) in text:
                return group.get("name"), place
    return None, None


def hard_filter(listing: Listing, settings):
    """Return (passes, reasons). `reasons` lists every rule the listing broke."""
    s = settings.get("search", {})
    reasons = []

    city = s.get("city")
    if city and listing.city and _norm(city) not in _norm(listing.city) and _norm(listing.city) not in _norm(city):
        reasons.append(f"עיר: {listing.city}")

    if listing.price is None:
        reasons.append("אין מחיר")
    else:
        if s.get("max_price") and listing.price > s["max_price"]:
            reasons.append(f"מחיר ₪{listing.price:,} מעל ₪{s['max_price']:,}")
        if s.get("min_price") and listing.price < s["min_price"]:
            reasons.append(f"מחיר ₪{listing.price:,} מתחת ל-₪{s['min_price']:,}")

    if listing.rooms is not None:
        if s.get("min_rooms") and listing.rooms < s["min_rooms"]:
            reasons.append(f"{listing.rooms:g} חדרים (מינימום {s['min_rooms']:g})")
        if s.get("max_rooms") and listing.rooms > s["max_rooms"]:
            reasons.append(f"{listing.rooms:g} חדרים (מקסימום {s['max_rooms']:g})")

    if s.get("min_size") and listing.size_sqm is not None and listing.size_sqm < s["min_size"]:
        reasons.append(f'{listing.size_sqm:g} מ"ר (מינימום {s["min_size"]})')

    if s.get("exclude_ground_floor") and listing.floor is not None and listing.floor <= 0:
        reasons.append("קומת קרקע")

    if s.get("area_mode", "require") == "require" and settings.get("areas"):
        group, _ = match_area(listing, settings)
        if group is None:
            reasons.append(f"מחוץ לאזורים: {listing.neighborhood or listing.street or 'לא ידוע'}")

    return not reasons, reasons
