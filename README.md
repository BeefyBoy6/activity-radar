# Activity Radar — Youth Activity Signup Tracker

Scrapes ~33 youth activity providers around Roseville, MN (55113) daily,
normalizes their program offerings into one database, and shows them in a
filterable dashboard. Alerts you when new sign-ups drop, when registration
windows open, and when one is about to open — so you never miss a window.

## Quick start

```powershell
cd youth-activity-tracker
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# seed the 33 sources + starter activities (from the July 2026 research docs)
python -m seed.seed

# run
uvicorn app.main:app --port 8033
```

Open http://localhost:8033 — the dashboard is served from the same process.
The daily scrape runs automatically at 6:00am CT while the server is up
(configurable via `AT_SCRAPE_HOUR`).

For JS-rendered sources (Rec1, Dash, ARUX, and some custom sites) also install
the headless browser once:

```powershell
pip install playwright
playwright install chromium
```

## Configuration

Copy `.env.example` → `.env`. Everything is optional:

- **Email alerts / daily digest** — set the `AT_SMTP_*` and `AT_EMAIL_*` vars.
  For Gmail, use an App Password (`smtp.gmail.com`, port 587).
- **Push notifications** — set `AT_NTFY_TOPIC` to a private topic name and
  subscribe to it in the [ntfy](https://ntfy.sh) mobile app.
- **LLM extraction** — set `AT_LLM_PROVIDER` (`anthropic` or `gemini`) +
  `AT_LLM_API_KEY` to dramatically improve extraction quality on the ~20
  custom sites (museums, theatres, clubs). Without it, a keyword-heuristic
  extractor is used.

Notification *preferences* (mute categories/orgs, toggle alert types) live in
the dashboard's Settings tab.

## How it works

```
sources (33, grouped by platform)
   │   daily 6am cron (APScheduler) or "Scrape now" button
   ▼
platform scrapers ──► normalizer ──► quality gate ──► differ (upsert + change events)
 rec1 / dash / eleyo / arux /            │
 revtrak / vscloud / ymca / custom       ├─► enricher (detail pages: full
                                         │    description, exact price/age/
                                         │    dates/location, direct link,
                                         │    dead-link cleanup)
                                         ├─► reg_opened / first_seen / opening_soon
                                         ▼
                              notifier (ntfy push + email + daily digest)
                                         ▼
                              FastAPI ──► dashboard (static SPA)
```

- **Enrichment**: after each scrape, the enricher visits every new/changed
  activity's own page (throttled, ~0.15s between fetches) and upgrades the
  record with the full description and precise fields. For Eleyo/ARUX it also
  reads the canonical course name (h1) and confirms real enrollability (an
  add-to-cart link = "open"). Dead detail links (404) are cleared so the card
  falls back to the org's catalog page — every card always has a working link.
- **Youth-only filtering**: adult/senior/driver's-ed categories are never
  crawled, and each Eleyo/ARUX course's breadcrumb ("Youth Enrichment / …"
  vs "Adult Enrichment") is checked on its detail page. Adult-audience
  courses are stored with `excluded=1` — permanently hidden from the
  dashboard, stats, and every notification, and never re-processed. The
  breadcrumb also refines the category tag (Science & Tech → stem, etc.).

- **Change detection** is the core: each scrape upserts by `(source, external_id)`
  and records `ActivityEvent`s. "New today" badges, the signup-history panel,
  and every notification derive from those events.
- Activities that disappear from a scrape are marked **stale**, not deleted,
  so history survives.
- A `registration_status` never downgrades to `unknown` once known.


## Data-quality safeguards

Every scraped candidate now passes a central quality gate before it can enter
the database or trigger a notification. The gate rejects generic page headings,
navigation, rentals, birthday-party packages, passes/memberships, services, and
clearly adult/senior offerings. It requires concrete evidence such as a youth
audience, activity-specific URL, age range, date/schedule, price, or registration
state. Custom/YMCA pages use a stricter threshold than structured registration
platforms.

Scrape logs show **accepted** and **rejected** counts plus the leading rejection
reasons. If a parser suddenly returns mostly noise or far fewer records than the
previous successful run, stale marking is skipped for safety instead of hiding
the whole catalog.

To audit records that were stored before the quality gate was added:

```powershell
# dry run; review data/quality-audit.csv
python -m scripts.quality_audit --csv data/quality-audit.csv

# after reviewing the CSV, hide rejected rows without deleting history
python -m scripts.quality_audit --apply --csv data/quality-audit.csv
```

The audit marks rows `stale=1`; it never deletes activities or events.

## Scraper reality check (read this once)

Platform scrapers are written against each platform's typical markup, but
selectors *will* need tuning after you watch the first real runs — that's
expected, and the Sources & Logs tab shows per-source errors precisely so you
can see which ones need attention. Tuning order that pays off fastest:

1. **Eleyo** (Roseville Community Ed) — server-rendered, most reliable.
2. **VS Cloud/WebTrac** (St. Paul) — plain HTML search results.
3. **YMCA North** — server-rendered Drupal pages.
4. **Rec1 / Dash / ARUX** — JS apps, need Playwright; inspect with devtools
   and adjust the CSS selectors in `app/scrapers/<platform>.py`.
5. **Custom sites** — heuristic keyword extraction; enable LLM extraction for
   much better results.

Test a single source from the command line:

```powershell
python -c "from app.database import SessionLocal; from app.services.runner import run_all; print(run_all(source_id=6))"
```

(or use the per-source **Scrape** button in the Sources tab).

## Docker

```bash
docker compose up -d --build
```

Serves on port 8033; SQLite lives in the `./data` volume.

## Project layout

```
app/
  main.py              FastAPI app + scheduler lifecycle
  config.py            env config
  models.py            Source / Activity / ActivityEvent / ScrapeLog / Setting
  api/routes.py        REST API
  scrapers/            one module per registration platform + custom fallback
  services/
    normalizer.py      age/price/date/status text parsing
    differ.py          upsert + change events (the "don't miss it" engine)
    runner.py          orchestrates scrapes + notifications
    notifier.py        email / ntfy / daily digest
    scheduler.py       APScheduler daily cron
    llm_extract.py     optional LLM extraction for messy sites
  static/              dashboard (vanilla JS SPA)
seed/seed.py           33 sources + starter activities
```

## Tests

```powershell
pip install -r requirements-dev.txt
pytest -q
```

The suite covers age/status normalization, URL safety, the activity-quality
gate, Eleyo/ARUX card isolation, audience exclusion, and database insertion.
