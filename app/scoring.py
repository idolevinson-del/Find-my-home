"""Transparent, deterministic match score.

Each criterion has a weight (settings.scoring) and yields a fraction of it:
  1.0 = matches, 0.0 = doesn't, 0.5 = unknown (the ad doesn't say).
Score = earned / possible * 100. Same inputs → same score, always.
The breakdown is what the UI and Telegram show as ✓ / ✗ / ?.
"""
from app.filters import match_area
from app.models import Listing

UNKNOWN = 0.5


def _item(key, label, fraction, weight, state=None):
    state = state or ("yes" if fraction >= 1 else "no" if fraction <= 0 else "unknown")
    return {"key": key, "label": label, "state": state,
            "points": round(weight * fraction, 2), "max": weight}


def _amenity(key, value, ai_value, yes_label, no_label, unknown_label):
    if value is True:
        return 1.0, yes_label, "yes"
    if value is False:
        return 0.0, no_label, "no"
    if ai_value is True:
        return 1.0, f"{yes_label} (לפי התיאור)", "yes"
    if ai_value is False:
        return 0.0, f"{no_label} (לפי התיאור)", "no"
    return UNKNOWN, unknown_label, "unknown"


def score_listing(listing: Listing, settings, ai=None):
    """Return (score 0-100, breakdown list)."""
    s = settings.get("search", {})
    prefs = settings.get("preferences", {})
    w = settings.get("scoring", {})
    ai = ai or {}
    items = []

    def add(key, label, fraction, state=None):
        weight = float(w.get(key, 0) or 0)
        if weight > 0:
            items.append(_item(key, label, fraction, weight, state))

    # Price
    if listing.price is not None and (not s.get("max_price") or listing.price <= s["max_price"]):
        add("price", f"מחיר ₪{listing.price:,} — בתקציב", 1.0)
    elif listing.price is not None:
        add("price", f"מחיר ₪{listing.price:,} — מעל התקציב", 0.0)
    else:
        add("price", "מחיר לא ידוע", UNKNOWN)

    # Area
    group, place = match_area(listing, settings)
    if group:
        add("area", f"אזור מועדף: {place}", 1.0)
    elif listing.neighborhood or listing.street:
        add("area", f"לא באזור מועדף ({listing.neighborhood or listing.street})", 0.0)
    else:
        add("area", "אזור לא ידוע", UNKNOWN)

    # Rooms
    if listing.rooms is None:
        add("rooms", "מספר חדרים לא ידוע", UNKNOWN)
    else:
        ok = (not s.get("min_rooms") or listing.rooms >= s["min_rooms"]) and \
             (not s.get("max_rooms") or listing.rooms <= s["max_rooms"])
        add("rooms", f"{listing.rooms:g} חדרים", 1.0 if ok else 0.0)

    # Size
    if listing.size_sqm is None:
        add("size", 'גודל לא ידוע', UNKNOWN)
    else:
        ok = not s.get("min_size") or listing.size_sqm >= s["min_size"]
        add("size", f'{listing.size_sqm:g} מ"ר', 1.0 if ok else 0.0)

    # Floor
    if listing.floor is None:
        add("floor", "קומה לא ידועה", UNKNOWN)
    elif listing.floor > 0:
        add("floor", f"קומה {listing.floor}", 1.0)
    else:
        add("floor", "קומת קרקע", 0.0)

    # Amenities (only when the user cares)
    for key, yes, no, unk in (("balcony", "מרפסת", "אין מרפסת", "מרפסת — לא צוין"),
                              ("parking", "חניה", "אין חניה", "חניה — לא צוין"),
                              ("elevator", "מעלית", "אין מעלית", "מעלית — לא צוין")):
        if prefs.get(key, "ignore") == "preferred":
            frac, label, state = _amenity(key, getattr(listing, key), ai.get(f"has_{key}"), yes, no, unk)
            add(key, label, frac, state)

    # Roommate fit — AI if available, otherwise a rooms-based estimate.
    roommates = int(prefs.get("roommates") or 0)
    if roommates:
        fit = ai.get("roommate_suitability")
        if fit in ("high", "medium", "low"):
            frac = {"high": 1.0, "medium": 0.5, "low": 0.0}[fit]
            add("roommate_fit", f"מתאימה ל-{roommates} שותפים ({ {'high': 'גבוה', 'medium': 'בינוני', 'low': 'נמוך'}[fit] })",
                frac, "yes" if frac == 1 else "no" if frac == 0 else "unknown")
        elif listing.rooms is not None:
            if listing.rooms >= roommates + 1:
                add("roommate_fit", f"כנראה מתאימה ל-{roommates} שותפים (לפי מספר החדרים)", 0.75, "yes")
            else:
                add("roommate_fit", f"מעט חדרים ל-{roommates} שותפים", 0.0)
        else:
            add("roommate_fit", f"התאמה ל-{roommates} שותפים — לא ידוע", UNKNOWN)

    # Broker
    if prefs.get("broker", "allowed_not_preferred") == "allowed_not_preferred":
        if listing.is_broker is False:
            add("no_broker", "ללא תיווך", 1.0)
        elif listing.is_broker is True:
            add("no_broker", "תיווך", 0.0)
        else:
            add("no_broker", "תיווך — לא ידוע", UNKNOWN)

    # Condition (AI only)
    cond = ai.get("condition")
    if cond in ("new", "renovated", "good"):
        add("condition", {"new": "חדשה", "renovated": "משופצת", "good": "במצב טוב"}[cond], 1.0)
    elif cond == "fair":
        add("condition", "מצב סביר", 0.5, "unknown")
    elif cond == "poor":
        add("condition", "דורשת שיפוץ", 0.0)
    else:
        add("condition", "מצב הדירה לא ידוע", UNKNOWN)

    possible = sum(i["max"] for i in items)
    earned = sum(i["points"] for i in items)
    score = round(100 * earned / possible) if possible else 0
    return score, items
