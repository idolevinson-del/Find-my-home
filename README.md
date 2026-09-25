# 🏠 Find My Home — Apartment Hunter TLV

A personal agent that looks for rental apartments in Tel Aviv. Set your
requirements once. It scans Yad2 in the background, scores each new listing
against your requirements, shows the results on a local dashboard, and sends a
Telegram message the moment a good match appears.

MVP: **Yad2 only**. Runs in GitHub's cloud (no computer needed) or locally.

## Running in the cloud (how it's set up now)

- `.github/workflows/hunt.yml` scans every 10 minutes. The database lives on
  the `bot-state` branch between runs.
- Alerts go to Telegram with **❤️ Save / ❌ Not for me** buttons.
- **Change the search by messaging the bot** in Hebrew: `תקציב 13000`,
  `חדרים 3.5-5`, `גודל 80`, `קרקע לא`, `הוסף אזור יפו`, `הסר אזור יפו`,
  `ציון 70`, `הגדרות`, `שמורות`, `עזרה`. Taps and commands are applied at the
  start of the next scan (within ~10 minutes).
- **Price drops** on listings you haven't rejected trigger a 🔻 alert.
- The dashboard is published to GitHub Pages after every scan:
  `https://<user>.github.io/<repo>/`. On the static site, Save/Reject are
  remembered on that phone. The Telegram buttons are the synced version.
- Secrets (repo Settings → Secrets → Actions): `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, and optionally `GEMINI_API_KEY`.
- One-time: Settings → Pages → Source: **GitHub Actions**.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in the Telegram values (see below)
python -m app.cli check-yad2   # make sure Yad2 answers from your network
python run.py               # → http://localhost:3000
```

`run.py` starts everything in one process: the SQLite DB (`data/hunter.db`), the
background scanner (every `SCAN_INTERVAL_MINUTES`, default 15) and the dashboard.
The **🔍 Scan now** button runs a scan immediately.

### Telegram (2 minutes)
1. In Telegram, open **@BotFather** → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` into `TELEGRAM_CHAT_ID`.
4. `python -m app.cli test-telegram` should send a message to your phone.

### AI (optional)
Put a Google AI Studio key in `GEMINI_API_KEY`. Gemini reads the ad text of **new
listings that passed the filters only** (at most 10 per scan). It estimates
roommate fit, condition and red flags, and fills in balcony/parking when the
structured data doesn't say. Without a key everything still works, and those
criteria just show as "unknown".

## Changing the search

Use the **⚙️ Settings** screen, or edit `config.yaml` directly. Both change the
same file. Changes apply immediately: every stored listing is re-filtered and re-scored.

| Setting | Meaning |
|---|---|
| `search.*` | Hard filters: rooms, price, min m², ground floor, and whether areas are **required** or only **preferred** |
| `areas` | Area groups → neighborhoods/streets, matched against the ad's neighborhood + street (Hebrew, as written on Yad2) |
| `preferences.*` | Roommates, balcony, parking, elevator, broker |
| `scoring.*` | Points per criterion (placeholders — tune them) |
| `notifications.*` | Minimum score for a Telegram alert, max alerts per scan, retries |
| `yad2.region` / `yad2.cities` | Yad2's numeric ids (see below) |

### Yad2 ids
The Yad2 feed needs a numeric `region` and `city`. `config.yaml` ships with
`city: 5000` (Tel Aviv–Yafo) and `region: 3`. **Verify these once on your machine:**

```bash
python -m app.cli lookup "תל אביב"
```

Copy the `cityId` into `yad2.cities` and the `regionId` into `yad2.region`.
`check-yad2` failing with HTTP 400 usually means a wrong region.

## How it works

```
Yad2 ─▶ Yad2Source (app/sources/yad2.py)      ← the only Yad2-specific code
          │ normalize → Listing (app/models.py)   unknown = None, never False
          ▼
       SQLite (app/db.py) — dedup on (source, source_id), change history
          ▼
       Hard filters (app/filters.py) ─▶ AI, new matches only (app/ai.py)
          ▼
       Match score + ✓/✗/? breakdown (app/scoring.py)
          ▼
   Dashboard (app/web)          Telegram outbox (app/notify/telegram.py)
```

- **New vs existing:** a listing is announced once, ever (a UNIQUE row in the
  `notifications` outbox). If it shows up again with a new price, the DB row is updated
  and the change is logged in `listing_changes`, ready for future "price dropped" alerts.
- **Telegram down?** The listing is already saved. The notification stays
  `pending` and is retried on the next scan (up to `max_attempts`).
- **Yad2 down or blocking?** The scan logs `yad2 request failed`, the dashboard
  shows a notice, and the next scan tries again. Nothing crashes.
- **Adding a source (Madlan, WinWin…):** subclass `BaseListingSource`
  (`search()`, `normalize()`, `get_listing()`), then add it in `pipeline.get_sources()`.

## Commands

```bash
python run.py                    # everything
python run.py --no-scan          # dashboard only
python -m app.cli scan           # one scan, in the terminal
python -m app.cli check-yad2     # connectivity + one parsed listing
python -m app.cli lookup "<text>"
python -m app.cli test-telegram
python -m pytest                 # tests
```

## Known limitations / to verify on first run
- Yad2 access depends on the `gw.yad2.co.il` feed and `curl_cffi`. If Yad2 changes
  or blocks it, only `app/sources/yad2.py` needs fixing.
- The full-ad endpoint used for descriptions (`realestate-item/<token>`) is
  unverified. If `check-yad2` works but descriptions stay empty and the log shows
  "details unavailable", set `yad2.fetch_details: false`.
- Amenities (balcony, parking…) come from the feed's tags. A missing tag means
  **unknown**, not "no".

See [NOTICE.md](NOTICE.md) for attribution and licensing notes.
