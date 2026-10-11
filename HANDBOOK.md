# Activity Radar — Owner's Handbook

The single reference for running, understanding, and improving Activity Radar.
README.md covers developer setup; AUDIT_REPORT.md records the July 2026 code
audit. This handbook covers everything else.

Last full revision: 2026-10-11.

---

## Contents

0. [Quick reference](#0-quick-reference)
1. [Action items as of this revision](#1-action-items-as-of-this-revision)
2. [How it works, in plain terms](#2-how-it-works-in-plain-terms)
3. [Glossary](#3-glossary)
4. [Where everything lives (file map)](#4-where-everything-lives-file-map)
5. [The data model](#5-the-data-model)
6. [The 33 sources](#6-the-33-sources)
7. [Using the dashboard](#7-using-the-dashboard)
8. [Configuration reference (.env)](#8-configuration-reference-env)
9. [Setting up notifications](#9-setting-up-notifications)
10. [Working on the site](#10-working-on-the-site)
11. [Running the server](#11-running-the-server)
12. [Keeping the data clean](#12-keeping-the-data-clean)
13. [Troubleshooting by symptom](#13-troubleshooting-by-symptom)
14. [Known issues and limitations](#14-known-issues-and-limitations)
15. [Improvement backlog (with prompts)](#15-improvement-backlog-with-prompts)
16. [Product direction notes](#16-product-direction-notes)
17. [Gotchas already discovered](#17-gotchas-already-discovered)
18. [History](#18-history)

---

## 0. Quick reference

| What | Where |
|---|---|
| Live site | https://activityradar.in (HTTP basic auth, user `ryan`) |
| Server | Gandi VPS `burger-combo-1`, `ubuntu@92.243.27.215`, Ubuntu 24.04 |
| App on the server | `/srv/activity-radar` (code), `/srv/activity-radar/data/tracker.db` (database), `/srv/activity-radar/.env` (secrets) |
| Service | systemd unit `activity-radar`, uvicorn on `127.0.0.1:8033` |
| Web front door | nginx site `/etc/nginx/sites-available/activity-radar`, password file `/etc/nginx/.htpasswd-activity-radar` |
| TLS certificate | Let's Encrypt, `/etc/letsencrypt/live/activityradar.in/`, auto-renews |
| Domain | `activityradar.in`, registered at Gandi (Gandi LiveDNS) |
| Code on your PC | `F:\[AI Dump]\claude code sample\youth-activity-tracker` |
| GitHub | https://github.com/BeefyBoy6/activity-radar (private), CI runs `pytest` on every push |
| Local dev URL | http://localhost:8033 |
| Daily scrape | 6:00 am America/Chicago, inside the app process |

The server also hosts other sites (including `jailroster.bigbeefslottools.com`).
They share nginx, so an nginx mistake for one site can affect the others.

---

## 1. Action items as of this revision

These were found while writing this handbook. Work them in order.

### 1.1 Restore HTTPS ✅ done 2026-10-11

Resolved: HTTPS re-applied, the password rotated, and all three sites on the
server verified. Kept for the record.

**What was wrong.** As of 2026-10-11, `https://activityradar.in` serves the
`jailroster.bigbeefslottools.com` certificate, so browsers refuse it. Plain
`http://` works and does not redirect. Every login sends the basic-auth password
in cleartext.

**Why it happened.** `deploy/setup-server.sh` copies the repo's nginx file over
the live one on every deploy. The repo file is HTTP-only; certbot had added the
HTTPS part to the live copy. The July audit deploy overwrote it, and nginx fell
back to another site's certificate.

**The fix in the repo** (committed alongside this handbook): the setup script
now re-applies the existing certificate after copying the nginx file, so future
deploys keep HTTPS.

**Fix the live server now** (SSH in first):

```bash
sudo certbot install --nginx --cert-name activityradar.in --redirect
curl -sI https://activityradar.in | head -1          # expect: HTTP/1.1 401 Unauthorized
curl -sI http://activityradar.in | grep -i location  # expect: Location: https://activityradar.in/
```

If certbot says no certificate named `activityradar.in` exists, issue a fresh
one instead: `sudo certbot --nginx -d activityradar.in --redirect`.

**Then rotate the password**, because it has crossed the network unencrypted.
Leave out `-c`; that flag would wipe the file:

```bash
sudo htpasswd /etc/nginx/.htpasswd-activity-radar ryan
```

### 1.2 Confirm the audit rollout finished on the server

The audit (PR #1) is deployed: the new nginx security headers are live. The
audit's rollout also has manual steps that can't be verified from outside the
password. Check them with section 12.1:

- [ ] Ran `python -m scripts.quality_audit` dry run, reviewed the CSV, then `--apply`
- [ ] Ran `python -m scripts.clean_titles` (preview, then `--apply`)
- [ ] Ran a full scrape and reviewed every source showing `warning` or `error`

### 1.3 Deploy the two fixes from this revision

Push, then deploy (section 10.4). The deploy carries the HTTPS-preserving setup
script and the seed fix described in section 14.

### 1.4 Turn on notifications

Notifications were never configured on the server, and they are the reason the
app exists. See section 9.

---

## 2. How it works, in plain terms

**The problem.** Registration for good kids' programs opens quietly and fills
fast. Activity Radar watches the providers so you don't have to remember to.

**The daily loop.** At 6 am a scheduler inside the app runs this pipeline for
each active source:

```
 provider website
       │  1. SCRAPE      one scraper per registration platform (8 scrapers, 33 sources)
       ▼
 raw candidates          loose dicts: "Grades 2nd-6th", "$199.00", "Register now"
       │  2. NORMALIZE   text → fields: ages 7–12, price 199, status "open"
       ▼
       │  3. QUALITY     reject menus, rentals, passes, adult classes, junk text
       ▼                 (rejections are counted and logged, never stored)
       │  4. DIFF        compare with yesterday → events: new / opened / changed
       ▼
 database (SQLite)
       │  5. ENRICH      visit each new/changed activity's own page: full
       │                 description, exact price/dates/location, audience check
       ▼
       │  6. NOTIFY      push + email: registration opened, opens within 48 h,
       ▼                 new activity; daily digest. Mutes respected.
 dashboard               activityradar.in reads the database
```

**What each step guarantees.**

1. **Scrape.** Sources are grouped by the registration *platform* they run on
   (ARUX, Rec1, Dash, WebTrac, RevTrak, YMCA North, plus a generic fallback), so
   33 sources need 8 scrapers. Scrapers stay deliberately simple and return raw
   data.
2. **Normalize.** All messy text parsing lives in one module, so every source
   gets identical rules for ages, prices, dates, and status. Status is only set
   from actionable phrases like "register now" or "registration opens". A
   stray "full-day camp" won't mark something as full.
3. **Quality gate.** Each candidate earns points for evidence that it is a real
   youth program: a specific title, ages, dates, price, registration language,
   or its own link. It must reach a threshold to get in. The threshold is 4 for
   structured platforms and 6 for generic websites. Navigation links, rentals,
   birthday packages, passes, and adult or senior offerings are rejected
   outright. The gate prefers missing a real program, which tomorrow's scrape
   can recover, over storing junk, which pollutes alerts and history.
4. **Diff.** Each activity has a stable ID, so the same program is recognized
   day to day. Changes become *events*, and everything you see derives from
   events: the "new today" badges, the history in each activity's detail view,
   and the notifications. Activities that vanish are marked *stale* (hidden),
   never deleted. If a scrape suddenly returns far fewer activities than usual,
   the app assumes the scraper broke. It skips the stale marking and logs a
   *warning* instead of hiding your whole catalog.
5. **Enrich.** Listing pages show summaries; each activity's own page has the
   truth. The enricher visits those pages, politely throttled, and upgrades the
   record. For Roseville Community Ed it also reads the page's breadcrumb, such
   as "Youth Enrichment" or "Adult Enrichment". Adult courses are permanently
   *excluded*: hidden from the dashboard, the stats, and every alert. Dead links
   (404) are cleared so the card falls back to the provider's catalog page.
6. **Notify.** Notification channels are push via ntfy and email via SMTP. Each
   event alerts once, and per-category and per-organization mutes are respected.

**Safety rails.** Only one scrape runs at a time: clicking "Scrape now" during
the 6 am run is ignored rather than doubling work and alerts. The app links you
to each provider's signup page but never registers or pays for you. Waivers and
payments stay human decisions.

---

## 3. Glossary

| Term | Meaning |
|---|---|
| **Source** | One provider you watch, such as "Shoreview YMCA". 33 are seeded. |
| **Platform** | The registration software a source runs on (ARUX, Rec1, …). Picks which scraper runs. |
| **Candidate** | A raw item a scraper found. It is not stored unless it passes the quality gate. |
| **Activity** | A stored program offering: name, ages, price, dates, status, signup link. |
| **Event** | A recorded change: `first_seen`, `reg_opened`, `status_change`, `reg_opening_soon`. Drives badges, history, and alerts. |
| **Registration status** | `not_yet_open`, `open`, `waitlist`, `closed`, or `unknown`. |
| **Stale** | Missing from the latest scrape. Hidden, with history kept. Comes back if it reappears. |
| **Excluded** | Confirmed non-youth (adult or senior). Hidden permanently, never alerted, never reprocessed. |
| **Enrichment** | The follow-up visit to an activity's own page for full detail. |
| **Quality gate** | The evidence-scoring checkpoint that decides whether a candidate becomes an activity. |
| **Seed row** | A starter activity typed in from the July 2026 research reports. External ID starts `seed-`. Illustrative, not scraped. See section 14. |
| **Warning (scrape)** | The scrape ran but looked suspicious (very low acceptance), so stale marking was skipped for safety. |

---

## 4. Where everything lives (file map)

```
youth-activity-tracker/
├── app/
│   ├── main.py              starts FastAPI + scheduler; creates/migrates DB tables
│   ├── config.py            reads .env (AT_* variables), categories list
│   ├── database.py          SQLite engine (WAL mode), ensure_schema() mini-migrations
│   ├── models.py            tables: sources, activities, activity_events, scrape_logs, settings
│   ├── api/routes.py        JSON API the dashboard calls
│   ├── scrapers/
│   │   ├── base.py          registry + fetch helpers (requests, Playwright)
│   │   ├── eleyo.py         Eleyo catalogs (crawls category pages, parses course cards)
│   │   ├── arux.py          ARUX = Eleyo's URL scheme; reuses eleyo.py (Roseville, Mounds View)
│   │   ├── rec1.py          Rec1/CivicRec catalogs (JS → Playwright)
│   │   ├── dash.py          Dash by DaySmart (Roseville Parks; JS → Playwright)
│   │   ├── vscloud.py       WebTrac (St. Paul Parks & Aquatics)
│   │   ├── revtrak.py       RevTrak web store (Arden Hills)
│   │   ├── ymca.py          YMCA North location pages
│   │   └── custom.py        generic fallback for museums/theatres/clubs (+ optional LLM)
│   ├── services/
│   │   ├── normalizer.py    ages / prices / dates / status / title cleanup
│   │   ├── quality.py       the quality gate (evidence scoring, rejection reasons)
│   │   ├── differ.py        upsert, change events, stale handling with safety check
│   │   ├── enricher.py      detail-page visits, audience check, dead-link cleanup
│   │   ├── runner.py        orchestrates a scrape run (with run lock) + notifications
│   │   ├── notifier.py      email, ntfy push, daily digest; applies mutes
│   │   ├── scheduler.py     APScheduler daily job
│   │   ├── settings_store.py dashboard settings with validation
│   │   └── llm_extract.py   optional Claude/Gemini extraction for messy pages
│   └── static/              the dashboard: index.html, styles.css, app.js (no build step)
├── seed/seed.py             the 33 sources + starter activities
├── scripts/
│   ├── quality_audit.py     re-check stored rows against the quality gate (dry run / --apply)
│   └── clean_titles.py      repair titles that absorbed description text (dry run / --apply)
├── tests/                   pytest suite (normalizer, quality gate, differ, enricher, parser)
├── deploy/
│   ├── setup-server.sh      idempotent server install/update (run on the server)
│   ├── activity-radar.service   systemd unit
│   ├── nginx-activity-radar.conf nginx site (HTTP; certbot adds HTTPS on the server)
│   └── deploy.ps1           older one-shot deploy helper (section 10.4 is preferred)
├── .github/workflows/tests.yml  CI: runs pytest on push and PRs
├── Dockerfile, docker-compose.yml  alternative container deployment (not what production uses)
├── requirements.txt / requirements-dev.txt
├── README.md, AUDIT_REPORT.md, HANDBOOK.md (this file)
└── .env.example             template for secrets; the real .env is never committed
```

**"Where do I look when…"**

- Dates or prices parse wrong → `services/normalizer.py`
- Junk is getting in, or real programs get rejected → `services/quality.py`
- One provider's results are off → `scrapers/<platform>.py`
- Wrong alerts → `services/differ.py` (events) and `services/notifier.py` (sending)
- Something looks wrong in the UI → `static/app.js` / `static/styles.css`

---

## 5. The data model

| Table | Holds | Key columns |
|---|---|---|
| `sources` | the 33 providers | `slug`, `platform`, `catalog_url`, `active`, `last_success_at`, `error_count` |
| `activities` | program offerings | `external_id` (stable per source), `name`, `category`, `age_min`/`age_max` (years; 0.75 = 9 months), `price`, `is_free`, `start_date`, `schedule_text`, `location`, `registration_status`, `registration_opens_at`, `signup_url`, `first_seen_at`, `stale`, `excluded`, `enriched_at` |
| `activity_events` | change history | `event_type`, `old_value` → `new_value`, `created_at`, `notified` |
| `scrape_logs` | one row per source per run | `status` (`ok`/`warning`/`error`), `activities_found` (accepted), `rejected_count`, `rejection_summary`, `staling_skipped`, `error` |
| `settings` | dashboard preferences | `zip`, `radius_minutes`, `muted_categories`, `muted_sources`, notification toggles |

The database is a single file. Copying it while the app runs is unsafe; use
`sqlite3 … ".backup …"` (section 11.3). New columns are added automatically at
startup by `ensure_schema()`, so updates never require manual migrations.

---

## 6. The 33 sources

**Verification status:** only **Roseville Area Schools Community Ed (ARUX)** has
been run and validated against the live site. The other scrapers were written
against each platform's typical markup and hardened by the audit, but each still
needs a first real run and review in Sources & Logs.

| Platform (scraper) | Sources | Notes |
|---|---|---|
| ARUX (`arux`) | Roseville Area Schools Community Ed (ISD 623) ✅, Mounds View Community Ed (ISD 621) | Server-rendered; no browser needed. ISD 623 moved off Eleyo in 2026. |
| Rec1 (`rec1`) | Little Canada, New Brighton, Mounds View Community Center, Shoreview Community Center | JS app → needs Playwright. Shoreview's site returns 403 to scripts. |
| Dash by DaySmart (`dash`) | Roseville Parks & Recreation | JS app → needs Playwright. |
| WebTrac / VS Cloud (`vscloud`) | St. Paul Parks & Rec, St. Paul Aquatics | Returns 403 to plain scripts, so the Playwright fallback is needed. |
| RevTrak (`revtrak`) | Arden Hills Parks & Rec | Server-rendered store pages. |
| YMCA North (`ymca`) | Shoreview, Maplewood, White Bear Area YMCAs | Program pages one level deep; stricter quality threshold. |
| Generic (`custom`) | Maplewood Youth & Adult Sports, Ramsey County Parks, Boys & Girls Clubs, MN JCC, YWCA St. Paul, Bell Museum, Science Museum, MN Children's Museum, The Works, Ramsey County Library, Maplewood Nature Center, Bakken Museum, Children's Theatre Co., Park Square Theatre, ArtStart, Schubert Club, MCAD Youth, i9 Sports, Adrenaline Sports Center, First Tee MN | Keyword heuristics with a strict threshold. Much better with LLM extraction enabled. |

URL corrections made during the July link audit: Children's Theatre moved to
`/education-and-engagement/for-children-and-families/classes-2/`, Bell Museum to
`/camps/`, MCAD to `/academics/continuing-education/summer-youth-courses-and-camps`,
and Adrenaline Sports Center's real domain is `adrenalinesc.com`.

**Not yet tracked, but relevant to Georgia** (found in your email history):
Minnesota Wild Learn to Play hockey (LeagueApps) and the annual USA Hockey
registration. See the backlog.

---

## 7. Using the dashboard

**Header stats.** Total visible activities, open now, not yet open, new in the
last 24 hours.

**Activities tab.**

- *Filters:* search (name and description), category, registration status,
  organization, child's age (defaults to 8; hides programs she doesn't qualify
  for, and keeps programs with unknown ages), free only, and sort.
- *Card badges:* green **Open**, yellow **Not yet open** with a ⏰ countdown,
  purple **Waitlist**, gray **Closed/Unknown**, blue **★ New today**.
- *Price:* `*` after a price means resident/member pricing differs; open the
  card for the breakdown.
- *Sign up ↗* opens that program's own registration page in a new tab.
- Click a card for full details plus **Signup history** (when it first appeared,
  when registration opened, and so on).

**Upcoming opens tab.** Every known registration-open date in order, grouped by
day ("opens today!", "opens in 3 days"). Below that, programs whose open date
hasn't been announced. This is the never-miss-it view.

**Sources & logs tab.** Every source with an on/off toggle (off = skipped
during scrapes), its activity count, last scrape time and status, and a
per-source **Scrape** button. The log shows accepted and rejected counts plus
the leading rejection reasons. A rising rejected count or a `warning` status is
your cue that a provider changed its website.

**Settings tab.** Zip/radius (informational for now), notification toggles,
muted categories and organizations. Mutes affect alerts only; muted items still
appear on the dashboard.

**⟳ Scrape now.** Runs every active source in the background. It takes several
minutes, because the enrichment step visits detail pages politely. A click made
while a scrape is already running is ignored.

---

## 8. Configuration reference (.env)

Lives at `/srv/activity-radar/.env` on the server. It is never committed. After
editing it, run `sudo systemctl restart activity-radar`. Every value is optional.

| Variable | Default | Purpose |
|---|---|---|
| `AT_DB_PATH` | `data/tracker.db` | Database file location (relative to the app folder) |
| `AT_ZIP` | `55113` | Default zip shown in Settings |
| `AT_RADIUS_MINUTES` | `15` | Default drive-time radius shown in Settings |
| `AT_TIMEZONE` | `America/Chicago` | Schedule time zone and "opens within 48 h" math |
| `AT_SCRAPE_HOUR` | `6` | Hour of the daily scrape (24 h clock) |
| `AT_SMTP_HOST` / `AT_SMTP_PORT` | — / `587` | Outgoing mail server (Gmail: `smtp.gmail.com`, 587) |
| `AT_SMTP_USER` / `AT_SMTP_PASSWORD` | — | Mail login; for Gmail, an **App Password**, not your account password |
| `AT_EMAIL_FROM` / `AT_EMAIL_TO` | — | Sender and recipient addresses for alerts and the digest |
| `AT_NTFY_TOPIC` | — | Private ntfy.sh topic name for phone push |
| `AT_LLM_PROVIDER` | — | `anthropic` or `gemini`; blank = off |
| `AT_LLM_API_KEY` / `AT_LLM_MODEL` | — | Key and optional model override for LLM extraction |

---

## 9. Setting up notifications

### Push to your phone (ntfy, free, about 5 minutes)

1. Install the **ntfy** app (iOS/Android).
2. Invent a long, unguessable topic name. Anyone who knows it can read your
   alerts, so something like `ar-georgia-7f3k29xq` works.
3. In the app: **Subscribe to topic** → enter that name.
4. On the server, set `AT_NTFY_TOPIC=ar-georgia-7f3k29xq` in `.env`, then restart.
5. Test from the server (it should buzz your phone):
   ```bash
   curl -d "Activity Radar test" https://ntfy.sh/ar-georgia-7f3k29xq
   ```

### Email and the daily digest (Gmail, about 10 minutes)

1. Turn on 2-Step Verification for the sending Google account (required for
   app passwords).
2. Google Account → Security → **App passwords** → create one named
   "Activity Radar" and copy the 16-character password.
3. In `.env`:
   ```
   AT_SMTP_HOST=smtp.gmail.com
   AT_SMTP_PORT=587
   AT_SMTP_USER=<sending gmail address>
   AT_SMTP_PASSWORD=<16-char app password>
   AT_EMAIL_FROM=<sending gmail address>
   AT_EMAIL_TO=<where you want alerts>
   ```
4. `sudo systemctl restart activity-radar`, then trigger a full scrape. The
   digest arrives when the run finishes.

**What you'll receive:** an instant alert when registration opens, when it
opens within 48 hours, and when a new activity appears. The daily digest
summarizes all three plus per-source scrape health. Each alert type can be
toggled in Settings.

---

## 10. Working on the site

### 10.1 Start a Claude Code session

```powershell
cd -LiteralPath "F:\[AI Dump]\claude code sample\youth-activity-tracker"
git pull                      # always start from the latest main
claude
```

Describe what you want, or paste a prompt from section 15. Claude keeps memory
of this project between sessions, so there's no need to re-explain it. Useful
habits:

- Ask Claude to **run it locally and show you** before anything ships.
- Ask for **tests** alongside any parser or quality-gate change.
- For a second opinion on a change, use `/code-review`.

### 10.2 Run and test locally

```powershell
python -m pip install -r requirements-dev.txt    # first time only
python -m seed.seed                               # first time, or after seed changes
python -m uvicorn app.main:app --port 8033        # → http://localhost:8033
python -m pytest -q                               # 20 tests as of this revision
```

Your local database (`data/tracker.db`) is separate from the server's, so
experiments are consequence-free. To try one source's scraper:

```powershell
python -c "from app.services.runner import run_all; print(run_all(source_id=6))"
```

(Source ids are shown in Sources & Logs; 6 = Roseville Community Ed.)

### 10.3 Branches, pull requests, and CI

For anything beyond a typo, use a branch:

```powershell
git checkout -b feature/ical-feed          # 1. branch from main
#   ...make and test changes...
git add -A
git commit -m "Add iCal feed of registration-open dates"
git push -u origin feature/ical-feed       # 2. publish the branch
```

3. On GitHub, open a **pull request** into `main`. CI runs the test suite
   automatically; a red ❌ means don't merge yet.
4. Read the diff on the PR page, or ask Claude to review it.
5. **Merge** on GitHub, then update your machine:
   ```powershell
   git checkout main
   git pull
   git branch -d feature/ical-feed
   ```

**The one rule: the server is only ever deployed from `main`.** Branches are
where risk lives; `main` is always deployable. The deploy method below enforces
this by packaging committed `main` only.

Branch naming that keeps things readable: `feature/…`, `fix/…`, `chore/…`.
Before a risky change, a safety bookmark like the existing
`backup/before-quality-fix` costs nothing:
`git branch backup/before-<thing>`.

### 10.4 Deploy to the Gandi server

From the project folder, on an up-to-date `main` with everything committed and pushed:

```powershell
git checkout main
git pull
git archive --format=tar.gz --prefix=youth-activity-tracker/ -o ..\activity-radar.tar.gz main
scp ..\activity-radar.tar.gz ubuntu@92.243.27.215:/tmp/
ssh ubuntu@92.243.27.215 "cd /tmp && rm -rf youth-activity-tracker && tar -xzf activity-radar.tar.gz && bash youth-activity-tracker/deploy/setup-server.sh /tmp/youth-activity-tracker"
```

`git archive` packages exactly what's committed on `main`: no `.git` history,
no `.env`, no local database, no caches. The setup script is idempotent. It
syncs the code, installs new dependencies, re-seeds sources (keeping existing
dates), restarts the service, refreshes nginx, and re-applies the HTTPS
certificate. **It never touches the server's database or `.env`.**

> Tip: each `scp`/`ssh` asks for your key passphrase. To type it once per
> boot, enable ssh-agent (section 17).

### 10.5 After every deploy (2-minute checklist)

```bash
systemctl status activity-radar | head -3             # → active (running) since <a moment ago>
curl -sI https://activityradar.in | head -1            # → HTTP/1.1 401 Unauthorized
curl -sI http://activityradar.in | grep -i location    # → redirects to https://
journalctl -u activity-radar --since "5 min ago" | tail -20   # no tracebacks
```

Then open the site, log in, and glance at Sources & Logs.

### 10.6 Rolling back

**Code** (the safe path, which keeps history):

```powershell
git revert HEAD        # creates a commit undoing the last one
git push
#   then deploy again (10.4)
```

**Data** (if a bad scrape or script damaged the database): stop the app,
restore a backup (11.3), start it.

---

## 11. Running the server

### 11.1 Cheat sheet (after `ssh ubuntu@92.243.27.215`)

```bash
systemctl status activity-radar                 # running? since when?
sudo systemctl restart activity-radar           # apply .env changes
journalctl -u activity-radar -f                 # live logs (Ctrl+C to stop)
journalctl -u activity-radar --since today | grep -E "scraped|failed|warning"
sudo nginx -t && sudo systemctl reload nginx    # after any nginx edit
sudo certbot certificates                       # list certs + expiry dates
sudo certbot renew --dry-run                    # prove auto-renewal works
df -h /                                         # disk space (Playwright is ~300 MB)
cd /srv/activity-radar && .venv/bin/python -c "from app.services.runner import run_all; print(run_all())"   # full scrape from the shell
```

### 11.2 Changing the dashboard password

```bash
sudo htpasswd /etc/nginx/.htpasswd-activity-radar ryan         # change (no -c!)
sudo htpasswd /etc/nginx/.htpasswd-activity-radar someone_else # add a second user
```

`-c` creates a new file and deletes every existing user. Use it only for the
very first user.

### 11.3 Backups and restore

**Manual backup** (safe while the app runs):

```bash
mkdir -p /srv/activity-radar/backups
sqlite3 /srv/activity-radar/data/tracker.db ".backup /srv/activity-radar/backups/tracker-$(date +%F).db"
```

**Nightly automatic backup, keeping 14 days.** Run `crontab -e` and add:

```
30 3 * * * sqlite3 /srv/activity-radar/data/tracker.db ".backup /srv/activity-radar/backups/tracker-$(date +\%F).db" && find /srv/activity-radar/backups -name 'tracker-*.db' -mtime +14 -delete
```

**Copy a backup to your PC** (offsite copy):

```powershell
scp ubuntu@92.243.27.215:/srv/activity-radar/backups/tracker-2026-10-11.db .
```

**Restore:**

```bash
sudo systemctl stop activity-radar
cp /srv/activity-radar/backups/tracker-YYYY-MM-DD.db /srv/activity-radar/data/tracker.db
rm -f /srv/activity-radar/data/tracker.db-wal /srv/activity-radar/data/tracker.db-shm
sudo systemctl start activity-radar
```

### 11.4 Routine maintenance

| How often | Task |
|---|---|
| Weekly (2 min) | Glance at Sources & Logs for `error`/`warning` rows |
| Monthly | `sudo apt update && sudo apt upgrade`, then `sudo reboot` if it says "restart required" (the app auto-starts) |
| Quarterly | `sudo certbot renew --dry-run`; check `df -h`; test-restore one backup locally |
| Each school season (Jan, Aug) | Run a manual full scrape early; that's when registration windows cluster |

---

## 12. Keeping the data clean

### 12.1 Audit stored rows against the quality gate

```bash
cd /srv/activity-radar
.venv/bin/python -m scripts.quality_audit --csv data/quality-audit.csv           # dry run
#   review data/quality-audit.csv (scp it to your PC to open in Excel)
.venv/bin/python -m scripts.quality_audit --apply --csv data/quality-audit.csv   # hide rejects
```

`--apply` marks rows stale. Nothing is deleted, and a later valid scrape can
restore a row.

### 12.2 Repair titles that swallowed descriptions

```bash
.venv/bin/python -m scripts.clean_titles              # preview
.venv/bin/python -m scripts.clean_titles --apply      # write
```

### 12.3 When junk gets through, or real programs are rejected

1. Find the source in Sources & Logs and read the rejection summary.
2. Junk getting in: add the pattern to `services/quality.py` (for example to
   `_NON_ACTIVITY`), **plus a test case in `tests/test_quality.py` using the
   real junk title**.
3. Real programs rejected: check which evidence is missing. Usually the scraper
   isn't capturing ages or the link, so the fix belongs in the scraper, not in
   a lower threshold.
4. A prompt that works: *"Here's the Sources & Logs output for <source>. These
   items shouldn't be there: … / these real programs are missing: … Fix it and
   add regression tests."*

### 12.4 Adding a new provider

1. **Same platform as an existing source:** add one entry to `SOURCES` in
   `seed/seed.py` with its catalog URL. Done.
2. **New platform:** add a scraper in `app/scrapers/` registered with
   `@register("<platform>")`, import it in `scrapers/__init__.py`, and add a
   parser test with a saved HTML fixture.
3. Deploy, then click that source's **Scrape** button and review its log
   before trusting its alerts.

---

## 13. Troubleshooting by symptom

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser says the connection isn't private / wrong certificate | HTTPS layer lost (section 1.1) | `sudo certbot install --nginx --cert-name activityradar.in --redirect` |
| Site won't load at all | Service down, or nginx broken | `systemctl status activity-radar`, `sudo nginx -t` |
| 502 Bad Gateway | nginx is up but the app isn't | `sudo systemctl restart activity-radar`; read `journalctl -u activity-radar -n 50` |
| Password prompt loops | Wrong password, or the htpasswd file was recreated | Reset it (11.2) |
| No 6 am scrape happened | Service was down overnight | Check `journalctl -u activity-radar --since yesterday`; run a manual scrape |
| One source shows `error` | Provider changed its site, or blocks scripts | Read the error in the log; ask Claude to fix that scraper |
| Source shows `warning` | Acceptance collapsed, so stale marking was skipped | The scraper probably broke; same as above. Your data was protected. |
| `playwright` errors in logs | Browser not installed on the server | `cd /srv/activity-radar && .venv/bin/playwright install --with-deps chromium` |
| No notifications arrive | `.env` not set, or the type is toggled off/muted | Section 9; check Settings toggles and mutes; look for `notifier` lines in the logs |
| Gmail rejects login | Used the account password | Use an App Password (section 9) |
| Adult classes showing | New adult category or wording slipped through | Section 12.3; add a test |
| Same program listed twice | The provider changed its URL/ID scheme | Ask Claude to inspect `external_id` for that source |
| "Scrape now" seems to do nothing | A scrape is already running | Wait; check the logs |
| PowerShell `cd` fails on the project path | `[` `]` are wildcards in PowerShell | `cd -LiteralPath "…"` |
| git: "dubious ownership" | F: drive doesn't record ownership | `git config --global --add safe.directory '<path>'` |

---

## 14. Known issues and limitations

- **Seed rows are illustrative, not scraped.** The 48 starter activities came
  from July 2026 research notes, with dates and prices that were *estimates*
  set relative to the day seeding ran. They help the dashboard look alive, but
  their dates and prices shouldn't be trusted. They retire on their own when
  their source scrapes successfully (they go stale), but they linger for
  sources that never scrape. Before this revision, every deploy also *reset*
  their dates relative to the deploy day. That is fixed: re-seeding now
  updates only names, descriptions, categories, locations, and links.
  Backlog item: retire seed rows entirely.
- **Only one source is live-verified** (Roseville Community Ed). The others
  need their first supervised run (section 6).
- **Basic auth is single-tier.** Anyone with the password is an admin: they can
  change settings, toggle sources, and trigger scrapes.
- **Zip/radius settings are informational.** Sources are a fixed list, not a
  geographic search.
- **Registration-open times are wall-clock local times**; the 48-hour window uses
  `AT_TIMEZONE`.
- **The CSP header blocks two inline `onclick` handlers** on Sign-up links. The
  links still work because the click handler ignores links, but the browser
  console logs CSP warnings. A cleanup item is in the backlog.
- **`datetime.utcnow()` is deprecated** in Python 3.12+; it works but warns.
- **The server runs a different Python than your PC** (3.12 vs 3.14). CI tests
  on 3.12, matching the server.
- **Provider websites change.** Every scraper will eventually break; the logs
  and warning status make breakage visible rather than silent.

---

## 15. Improvement backlog (with prompts)

Paste a prompt into a Claude Code session in this folder. Items done by the July
audit are marked ✅ so you don't redo them.

### Already done
✅ Parser and quality-gate tests + CI · ✅ nginx rate limiting and security headers
· ✅ Central quality gate with rejection logging · ✅ Scrape run lock + SQLite WAL
· ✅ Stale-marking safety check · ✅ New-activity alerts implemented

### Security

| Item | Why | Prompt |
|---|---|---|
| HSTS header | After HTTPS is restored, stops browsers ever falling back to HTTP | "HTTPS is confirmed working on activityradar.in. Add an HSTS header to the 443 server block in a way that survives certbot and our deploy script." |
| Nightly backups | The database is the app's memory | "Add the nightly SQLite backup cron from HANDBOOK 11.3 to setup-server.sh, idempotently, and add an offsite copy option." |
| fail2ban for 401s | Rate limiting slows guessing; fail2ban stops it | "Add a fail2ban jail on the gandi server for repeated nginx 401s on activityradar.in. Walk me through it safely." |
| SSH hardening | Key-only login, no root | "Audit sshd_config on the gandi server for key-only auth and no root login. Walk me through applying it without locking myself out." |
| Dependency audit | Scrapers parse untrusted HTML | "Run pip-audit on requirements.txt, upgrade anything flagged, and run the tests." |
| Split viewer/admin | One password = full control | "Make the dashboard read-only by default and put settings/scrape controls behind a second admin password." |

### Correctness and code quality

| Item | Why | Prompt |
|---|---|---|
| Retire seed rows | Estimated dates shouldn't sit beside real data | "Stop seeding starter activities (keep the 33 sources), mark existing seed- rows stale, and make the dashboard look right when empty." |
| Remove inline onclick | CSP blocks them; console noise | "Remove the inline onclick handlers in app.js so the page is fully CSP-compliant, and verify no console errors." |
| utcnow() cleanup | Deprecated | "Replace datetime.utcnow() across the app with timezone-aware UTC, keeping stored values compatible." |
| Real migrations | ensure_schema only adds columns | "Introduce Alembic migrations, baselined on the current schema, replacing ensure_schema." |
| Scraper health alert | A broken scraper should page you | "Send an alert when any source errors or warns 2 days in a row." |
| Supervised first runs | 32 sources unverified | "Let's verify the <platform> scraper: run it for <source>, show me accepted and rejected results, and fix selectors with fixture-based tests." |

### UX / UI

| Item | Why | Prompt |
|---|---|---|
| Calendar feed | Registration dates inside your real calendar | "Add a token-protected /calendar.ics feed of registration-open dates and program start dates that I can subscribe to from Google Calendar." |
| Star / pipeline | Track watching → registered → done | "Add a per-activity star and a pipeline status (watching/registered/passed) with its own tab." |
| Dismiss | Some cards are permanent noise | "Add a dismiss button that hides a card permanently, with a 'show dismissed' toggle." |
| Phone app feel | You check from your phone | "Make the dashboard an installable PWA with icons, and polish the 375px layout." |
| Multi-kid profiles | Different ages and interests | "Add child profiles (age + interest tags) with a switcher that drives the filters." |

### Coverage and features

| Item | Why | Prompt |
|---|---|---|
| **Notifications** | The whole point | "Walk me through ntfy + Gmail setup on the server per HANDBOOK section 9, then send a test alert." |
| LLM extraction | 20 generic sources are hard to parse | "Enable the Anthropic LLM extractor for custom sources with a monthly cost cap, and compare results with the heuristic." |
| Wild hockey | Georgia is enrolled; LeagueApps isn't tracked | "Add a LeagueApps scraper for Minnesota Wild Learn to Play, plus an annual USA Hockey registration reminder." |
| Season preview | Camps open Jan–Mar | "Each January, surface last year's summer-camp providers before their pages update." |
| Free & almost free view | Serves families on a budget | "Add a 'Free & almost free' view and a monthly email roundup of $0 programs." |

---

## 16. Product direction notes

Ideas discussed in July 2026, in case Activity Radar grows beyond one family.

- **Start with a free weekly email** ("Opens This Week" for NE metro parents).
  It's a template over existing data, and it tests demand before any big build.
- **Freemium later:** keep discovery free; charge for convenience (personal
  alerts, SMS, multi-kid planning, calendar sync), roughly $30–40/yr.
- **Seasonal product:** a summer-camp planner sold in December, when camp
  registration panic starts.
- **Provider side, only once there's an audience:** featured placement,
  "fill this session" promos.
- **Always link out:** show facts (name, ages, price, dates) and send parents to
  the provider's own signup page. Don't republish their full descriptions or
  photos, and never take registrations yourself. This keeps you on the right
  side of copyright and makes providers allies.
- **Serve broadly:** free programs, logistics tags (busing, full-day coverage),
  language access (Hmong, Somali, Spanish), and adaptive programs are real,
  unmet needs. Partners worth calling: Sprockets (St. Paul), Ramsey County
  Library, school community ed offices.
- **Before charging money:** talk to five parents unlike you, spend 30 minutes
  with a lawyer on scraping/terms of service, and treat reliability (tests,
  backups, scraper health alerts) as a product promise.
- **Avoid:** display ads, selling data, and storing children's names.

---

## 17. Gotchas already discovered

- **PowerShell and `[AI Dump]`:** square brackets are wildcards. Use
  `cd -LiteralPath "…"`. git itself doesn't care.
- **The F: drive (exFAT) records no ownership**, so git required the
  `safe.directory` exception. It's already configured; on a new PC run
  `git config --global --add safe.directory '<path>'`.
- **Your Desktop is in OneDrive:** `C:\Users\ryand\OneDrive\Desktop`.
- **SSH key passphrase prompts every time** because ssh-agent is disabled.
  One-time fix in an *elevated* PowerShell:
  ```powershell
  Set-Service ssh-agent -StartupType Automatic
  Start-Service ssh-agent
  ssh-add $env:USERPROFILE\.ssh\id_ed25519
  ```
- **Deploys overwrite the live nginx file.** Fixed by re-applying certbot in the
  setup script, but if you ever hand-edit nginx on the server, put the change in
  `deploy/nginx-activity-radar.conf` too, or the next deploy erases it.
- **One broken nginx file blocks every site.** The server's sites share one
  nginx. On 2026-10-11 the Lot Log file (`/etc/nginx/sites-available/lot-log`)
  had a `sudo tee … << 'EOF'` command pasted into it, which made `nginx -t`
  fail. That blocked certbot and reloads for all sites, and a reboot would have
  taken all three offline. After editing any nginx file, run `sudo nginx -t`
  before anything else. Never paste a command while a file is open in an
  editor. Before rebooting, `sudo nginx -t` must pass.
- **Terminal output pasted into a chat may show web addresses as
  `[x](https://x)`.** That's the chat's formatting, not the file's contents.
  Don't "fix" it on the server.
- **Before 2026-10-11, deploys didn't restart the app.** `setup-server.sh`
  used `systemctl enable --now`, which won't restart an already-running
  service, so new code only took effect after a reboot. It now restarts
  explicitly. To check after any deploy, `systemctl status activity-radar`
  should show "active (running) since" a moment ago.
- **Every deploy runs `seed.seed`.** Seed changes reach the server on each
  deploy, and only static fields refresh.
- **Uncommitted files can vanish.** The first handbook was never committed and
  was lost. Commit early; push often.
- **Some providers block scripts (403)** but work in browsers: St. Paul WebTrac
  and Shoreview Community Center. These need the Playwright path; it isn't a
  breakage.
- **ISD 623 moved from Eleyo to ARUX** in 2026. `isd623.ce.eleyo.com` is an
  empty shell; the real catalog is `roseville.arux.app`.
- **ARUX quirks:** `/courses` returns 404 (start from the tenant homepage); card
  anchors wrap the whole card text, so titles come from the URL slug or the
  detail page's `<h1>`; an `/cart/add/` link on a detail page means genuinely
  enrollable.
- **DNS changes at Gandi take up to about 3 hours** (TTL), and `resolvectl
  flush-caches` can't speed up upstream caches. The truth, immediately:
  `dig +short A activityradar.in @ns-29-a.gandi.net`.
- **New domains at Gandi start pointed at Gandi's parking server**
  (`217.70.184.38`); replace that A record before running certbot.
- **The Python versions differ:** 3.14 locally, 3.12 on the server and in CI.

---

## 18. History

| Date | Milestone |
|---|---|
| 2026-07-10 | Built: 33 sources, 8 scrapers, dashboard, notifications engine. Discovered ISD 623 moved to ARUX; first live ingest of Roseville Community Ed. |
| 2026-07-10 | Added detail-page enrichment, the link audit (4 broken provider URLs fixed), and youth-only filtering after adult classes were spotted. |
| 2026-07-11 | Deployed to the Gandi VPS; registered `activityradar.in`; HTTPS via Let's Encrypt; basic auth. |
| 2026-07-11 | First handbook written (uncommitted; later lost). Repo created on GitHub. |
| 2026-07-18 | External code audit, merged as PR #1 (`fix/scrape-quality`): quality gate, parser fixes, tests + CI, stale safety, run lock, nginx hardening. See AUDIT_REPORT.md. |
| 2026-10-11 | This handbook. Found and fixed: HTTPS lost on deploy (setup script now re-applies the cert) and seed dates reset on each deploy (now only static fields refresh). On the server: repaired the corrupted Lot Log nginx file that was blocking certbot, restored HTTPS, rotated the dashboard password. |
