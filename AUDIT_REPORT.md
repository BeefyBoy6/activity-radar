# Activity Radar Code Audit and Repair Report

Date: 2026-07-18

## Executive summary

The main data-quality failure was architectural: every scraper candidate with a
non-empty name was normalized and written to SQLite before the app asked whether
it was actually a youth activity. Several scrapers also used broad CSS selectors
and climbed into containers containing multiple cards, so navigation, rentals,
passes, services, adult exercise classes, and neighboring-card text could become
activities.

This repair adds a conservative quality checkpoint before insertion, improves
platform parsing and adult-audience verification, exposes rejection information
in the dashboard, and prevents a broken scrape from mass-staling the existing
catalog.

The supplied database contained 142 active rows. A dry-run audit now identifies
12 likely non-activity/adult rows. They are listed in `data/quality-audit.csv`.
The original rows were not deleted or hidden automatically.

## Highest-impact defects found

### 1. No candidate quality gate — fixed

`differ.apply_scrape()` previously accepted every normalized row with a title.
The new `app/services/quality.py` scores evidence and hard-rejects common noise:

- navigation and generic landing-page titles;
- rentals and birthday-party packages;
- punch/season passes and memberships presented as products;
- services such as early-childhood screening and meal registration;
- clearly adult/senior offerings;
- candidates lacking enough program, youth, date, price, status, or direct-link
  evidence.

Custom and YMCA pages use a stricter threshold than structured registration
platforms.

### 2. Eleyo/ARUX cards absorbed neighboring listings — fixed

The previous parser climbed parent nodes based only on text length. A parent
could contain several course links, causing one activity to inherit another
activity's age, description, price, or status. This is visible in the supplied
DB: several early Roseville rows share the same multi-course description and
incorrect age text.

The parser now stops climbing when a parent contains multiple course links and
stops at semantic card/article boundaries. It also supports both ARUX URL forms:
`/course/<id>/...` and `/course/<category>/<id>/...`.

### 3. Age extraction swallowed arbitrary prose — fixed

The prior regex captured up to 25 word characters after `Ages`/`Grades`, creating
values such as `9+ Students will learn`, `care program`, and location fragments.
Age extraction now returns compact recognized phrases and discards unparseable
captures. Month ranges such as `9-24 months` remain month-aware.

### 4. Registration status produced false positives — fixed

A generic `register` or `full` anywhere in a page could mark a candidate open or
waitlisted. `full-day camp` and `closed-toe shoes` were vulnerable examples.
Status parsing now requires actionable phrases such as `registration is open`,
`register now`, `registration opens`, `join the waitlist`, or `registration is
closed`.

### 5. Adult filtering depended on a fragile breadcrumb regex — fixed

The detail parser now checks actual breadcrumb-like DOM elements plus title and
page-introduction evidence. Adult Enrichment, senior, 18+/21+/55+ pages are
excluded unless the title/category contains explicit youth evidence.

### 6. Generic pages were repeatedly “enriched” as activity pages — fixed

Many custom/SPA rows point only to an organization catalog or homepage. The old
enricher fetched that same generic page once per activity and could import its
metadata as an activity description. Generic source URLs are now recognized and
skipped.

Transient 429/5xx/network failures are left eligible for retry. Permanent 404/410
links are cleared, and intentionally unavailable 400/401/403 detail pages are
not retried every morning.

### 7. Unstable external IDs created duplicates — fixed

Several scraper IDs included full card text, so a price/status change changed the
hash and created a new activity rather than updating the old one. Scrapers now
prefer provider IDs and activity-specific URLs; fallback hashes avoid volatile
status/description text.

### 8. A partial parser failure could stale almost the whole source — fixed

Previously, one accepted row was enough to mark every other row missing/stale.
Stale updates are now skipped when candidate acceptance is too low or source
coverage collapses unexpectedly. The scrape is logged as a warning for review.

### 9. Scrape observability was incomplete — fixed

`ScrapeLog` now records:

- accepted candidates;
- rejected candidates;
- leading rejection reasons;
- whether stale marking was skipped for safety.

The Sources & Logs dashboard displays those fields.

### 10. Concurrent scrape requests could overlap — fixed

A process-wide lock prevents a scheduler run and one or more manual button clicks
from running together, reducing duplicate notifications and SQLite contention.
SQLite now uses WAL mode, foreign keys, and a 30-second busy timeout.

### 11. Notification/settings defects — fixed

- The `notify_new` setting existed but was never used. New-activity push/email
  alerts are now implemented.
- Daily digests did not apply mute rules to opened/soon activities. They do now.
- ntfy HTTP failures are now detected with `raise_for_status()`.
- Corrupt or malformed stored settings no longer crash the settings API.

### 12. Deployment configuration referenced the wrong domain — fixed

The nginx and Certbot instructions still referenced
`activities.bigbeefslottools.com`, while the handbook identifies the live site as
`activityradar.in`. Deployment files now use `activityradar.in`, install missing
server prerequisites, and add rate limiting and basic browser security headers.

## Supplied-database audit

Dry-run command:

```powershell
python -m scripts.quality_audit --csv data/quality-audit.csv
```

Result: **12 of 142 active rows** were rejected. The report currently includes:

- Early Childhood Screening;
- Disco Splash, Swimnastics, H2O Cardio, and Water Exercise pass offerings;
- Pool/Gym Birthday Party Packages;
- Lap/Open Swim 5-Punch Pass;
- four `Let's Do Lunch` service listings.

Review `data/quality-audit.csv`, then hide those rows without deleting history:

```powershell
python -m scripts.quality_audit --apply --csv data/quality-audit.csv
```

The command sets `stale=1`. It does not delete activities or events, and a later
valid scrape can restore a row.

## Verification performed

- `pytest -q`: **15 tests passed**.
- `python -m compileall -q app seed scripts tests`: passed.
- JavaScript syntax: `node --check app/static/app.js`: passed.
- API route smoke test against a temporary seeded SQLite DB:
  `/api/meta`, `/api/activities`, `/api/sources`, and `/api/logs` all returned
  HTTP 200.
- The audit script was tested in dry-run mode on the supplied DB and in apply
  mode on a temporary copy; apply mode reduced visible rows from 142 to 130.

A live scrape against provider websites was not run in this sandbox because it
has no external DNS/network access. Selectors should still be verified source by
source after deployment.

## Recommended rollout

1. Back up the production database:

   ```bash
   sqlite3 /srv/activity-radar/data/tracker.db ".backup /srv/activity-radar/backups/pre-quality-fix.db"
   ```

2. Deploy the code but do not apply the existing-row audit yet.
3. Run locally or on the server:

   ```bash
   python -m scripts.quality_audit --csv data/quality-audit.csv
   ```

4. Review the CSV, then run it again with `--apply`.
5. Scrape only Roseville Community Ed first and inspect accepted/rejected counts:

   ```bash
   python -c "from app.services.runner import run_all; print(run_all(source_id=6))"
   ```

6. Confirm adult exercise, rentals, passes, screening, and lunch-service rows are
   hidden while actual camps/classes remain.
7. Run the full scrape and review any source with `warning` status before relying
   on notifications.

## Known limitations

- Generic custom-site scraping is intentionally conservative and may miss a real
  program when a page provides no youth, age, date, price, status, or direct-link
  evidence. Enabling the optional LLM extractor can improve recall, but its output
  still passes through the deterministic quality gate.
- Rec1, Dash, VS Cloud, RevTrak, YMCA, and custom selectors still require live
  provider-site validation because their markup can change.
- The quality gate includes a small title list for known adult aquatics noise from
  the supplied DB. The ARUX breadcrumb check is the broader long-term safeguard.
- Registration-open timestamps remain local wall-clock values. Opening-soon
  comparisons now use the configured `AT_TIMEZONE` to avoid UTC offset errors.
