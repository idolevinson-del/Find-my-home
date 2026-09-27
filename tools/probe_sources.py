"""Check which listing sites answer from this network (read-only, a few requests).

    python tools/probe_sources.py

Prints one verdict line per site. Nothing is saved and no login is used.
"""
import sys

from curl_cffi import requests as http

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEAD = {"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9,en;q=0.7"}

MADLAN_QUERY = {
    "operationName": "searchPoi",
    "variables": {"dealType": "unitRent", "roomsRange": [4, 4], "locationDocId": "תל-אביב-יפו-ישראל",
                  "poiTypes": ["bulletin"], "offset": 0, "limit": 5},
    "query": "query searchPoi($dealType: String, $roomsRange: [Float], $locationDocId: String, "
             "$poiTypes: [PoiType], $offset: Int, $limit: Int) { searchPoiV2(dealType: $dealType, "
             "roomsRange: $roomsRange, locationDocId: $locationDocId, poiTypes: $poiTypes, offset: $offset, "
             "limit: $limit) { total poi { id ... on Bulletin { price beds area addressDetails { neighbourhood } } } } }",
}


def verdict(name, r, err=None, extra=""):
    if err is not None:
        print(f"[ {name} ]  אין תשובה ({type(err).__name__}): {str(err)[:120]}")
    elif r.status_code == 200:
        print(f"[ {name} ]  עובד ✓  (HTTP 200, {len(r.content):,} bytes) {extra}")
    elif r.status_code in (401, 403, 429) or "px" in "".join(r.cookies.keys()).lower():
        print(f"[ {name} ]  חסום ✗  (HTTP {r.status_code}) {r.text[:80]!r}")
    else:
        print(f"[ {name} ]  תשובה לא צפויה (HTTP {r.status_code}) {r.text[:80]!r}")


def call(method, url, **kw):
    try:
        return getattr(http, method)(url, impersonate="chrome124", timeout=20, headers=HEAD, **kw), None
    except Exception as e:
        return None, e


print("בודק... (עד דקה)\n")

r, e = call("get", "https://gw.yad2.co.il/realestate-feed/rent/feed?region=3&city=5000&maxPrice=12000")
verdict("יד2 (לבדיקת השוואה)", r, e)

r, e = call("get", "https://www.madlan.co.il/for-rent/%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95-%D7%99%D7%A9%D7%A8%D7%90%D7%9C")
verdict("מדלן - דף חיפוש", r, e)
cookies = r.cookies if r is not None else None
r, e = call("post", "https://www.madlan.co.il/api2", json=MADLAN_QUERY, cookies=cookies,
            headers={**HEAD, "origin": "https://www.madlan.co.il", "x-source": "web",
                     "referer": "https://www.madlan.co.il/for-rent/"})
extra = ""
if r is not None and r.status_code == 200:
    try:
        extra = f"total={r.json()['data']['searchPoiV2']['total']}"
    except Exception:
        extra = "(אבל בלי נתוני דירות)"
verdict("מדלן - נתוני דירות", r, e, extra)

r, e = call("get", "https://www.winwin.co.il/")
verdict("WinWin - דף הבית", r, e)
r, e = call("get", "https://www.winwin.co.il/RealEstate/ForRent/RealEstatePage.aspx")
verdict("WinWin - נדל\"ן להשכרה", r, e)

print("\nסיימתי. שלח צילום מסך של השורות למעלה.")
