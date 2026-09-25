# Third-party notice

## EladNa1/Apartment-Bot — https://github.com/EladNa1/Apartment-Bot

The Yad2 access approach in `app/sources/yad2.py` is adapted from Apartment-Bot:
the `gw.yad2.co.il` realestate-feed endpoint and its parameters, the listing JSON
shape (`token`, `address.*`, `additionalDetails.*`, `metaData.images`, `tags`), the
feed's promotion buckets, and fetching with `curl_cffi`'s Chrome TLS profile.
The Gemini REST call in `app/ai.py` follows the same approach as its `llm.py`.
The code in this repository was rewritten, not copied file-for-file.

**License status: unclear.** When this project was started (2026-09-25), the
Apartment-Bot repository had **no LICENSE file** and its README does not state a
license. Without a license, the default is "all rights reserved". Before making
this repository public or distributing it, confirm the license with the author
(or remove the adapted parts).

## cxt9/find-apartments — https://github.com/cxt9/find-apartments (MIT per README)

Used only as an architecture reference for future multi-source support
(Madlan / WinWin / Facebook). No code copied.

## Data sources

Being able to reach a site's data technically does not mean every use is
permitted. Check Yad2's terms of use. This project fetches at a low rate
(default every 15 minutes, minimum 5, a few seconds between requests) and does
not attempt to bypass blocks.
