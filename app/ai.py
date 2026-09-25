"""Gemini analysis of the unstructured part of an ad (description text).

Only runs on listings that already passed the hard filters. Never used for
anything we can compute (price, rooms, floor...). Anything the ad doesn't say
must come back as "unknown"/null — the prompt forbids guessing, and we validate.
REST call via `requests` (same approach as Apartment-Bot's llm.py), no SDK.
"""
import json
import logging

import requests

from app.config import secret

log = logging.getLogger("hunter")

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """You analyze a rental apartment ad from Tel Aviv (usually Hebrew) for someone looking \
for a place for {roommates} roommates. Use ONLY what the ad says. If something is not stated \
or clearly implied, answer "unknown" (or null for booleans). Never invent facts.

Return JSON with exactly these keys:
{{
  "roommate_suitability": "high" | "medium" | "low" | "unknown",
  "condition": "new" | "renovated" | "good" | "fair" | "poor" | "unknown",
  "has_balcony": true | false | null,
  "has_parking": true | false | null,
  "has_elevator": true | false | null,
  "likely_noise_level": "low" | "medium" | "high" | "unknown",
  "couples_only": true | false | null,
  "small_room_warning": true | false | null,
  "red_flags": [short strings, in Hebrew],
  "positive_points": [short strings, in Hebrew],
  "summary": "one short sentence in Hebrew"
}}

Ad:
title: {title}
neighborhood: {neighborhood}
street: {street}
price: {price}
rooms: {rooms}
size_sqm: {size_sqm}
floor: {floor}
structured amenities (null = not stated): parking={parking}, balcony={balcony}, elevator={elevator}
description:
\"\"\"{description}\"\"\"
"""

ENUMS = {
    "roommate_suitability": {"high", "medium", "low", "unknown"},
    "condition": {"new", "renovated", "good", "fair", "poor", "unknown"},
    "likely_noise_level": {"low", "medium", "high", "unknown"},
}
BOOLS = ("has_balcony", "has_parking", "has_elevator", "couples_only", "small_room_warning")


def enabled(settings):
    return bool(settings.get("ai", {}).get("enabled") and secret("GEMINI_API_KEY"))


def validate(raw):
    """Coerce the model output into our schema; anything off-schema becomes unknown."""
    out = {}
    for k, allowed in ENUMS.items():
        v = raw.get(k)
        out[k] = v if v in allowed else "unknown"
    for k in BOOLS:
        v = raw.get(k)
        out[k] = v if isinstance(v, bool) else None
    for k in ("red_flags", "positive_points"):
        v = raw.get(k)
        out[k] = [str(x) for x in v][:8] if isinstance(v, list) else []
    out["summary"] = str(raw.get("summary") or "")[:300]
    return out


def analyze(listing, settings, session=requests):
    """Return the validated analysis dict, or None if AI is off / the call failed."""
    if not enabled(settings):
        return None
    cfg = settings.get("ai", {})
    prompt = PROMPT.format(roommates=settings.get("preferences", {}).get("roommates", 3),
                           description=(listing.description or "")[:4000],
                           **{k: getattr(listing, k) for k in (
                               "title", "neighborhood", "street", "price", "rooms", "size_sqm",
                               "floor", "parking", "balcony", "elevator")})
    try:
        r = session.post(
            ENDPOINT.format(model=cfg.get("model", "gemini-flash-latest")),
            params={"key": secret("GEMINI_API_KEY")},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}},
            timeout=45)
        if r.status_code != 200:
            log.warning(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
            return None
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return validate(json.loads(text.strip().strip("`").removeprefix("json")))
    except Exception as e:
        log.warning(f"Gemini analysis failed: {e}")
        return None
