"""Post-scrape enrichment: visit each activity's detail page and upgrade the
record with the full description, precise price/age/date/schedule/location,
and a refined registration status.

Listing cards only carry truncated context text; the detail page is the
source of truth. Runs after each scrape for activities not yet enriched
(or re-flagged by the differ), throttled to be polite.
"""
from __future__ import annotations

import logging
import re
import time

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from ..config import REQUEST_TIMEOUT, USER_AGENT
from ..models import Activity, ActivityEvent, Source, utcnow
from .normalizer import parse_age_range, parse_date, parse_price

log = logging.getLogger("enricher")

BATCH_LIMIT = 320      # max detail pages per source per run
DELAY_S = 0.15         # politeness delay between fetches

_ORDINAL = re.compile(r"(\d)(st|nd|rd|th)\b", re.I)


def _fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def _clean(text: str) -> str:
    return _ORDINAL.sub(r"\1", text)


# --------------------------------------------------------------------------
# platform detail parsers — each returns a partial dict of Activity fields
# --------------------------------------------------------------------------

# breadcrumb program areas that mean the course is not for kids
ADULT_CRUMB = re.compile(r"^(adult|senior|driver|community education for adults|55\+|21\+)", re.I)

# youth-enrichment subcategory -> app category
CRUMB_CATEGORY = [
    (re.compile(r"science|tech|academic|stem|math", re.I), "stem / education"),
    (re.compile(r"creative|art|music|theat|dance", re.I), "creative arts"),
    (re.compile(r"health|wellness|sport|athletic|gym|ninja|fitness", re.I), "athletics"),
    (re.compile(r"aquatic|swim", re.I), "aquatics"),
]


def parse_eleyo_arux_detail(url: str) -> dict:
    """Eleyo/ARUX /course/<id> pages: description paragraphs up top, then an
    Options block with Starts/times/location/Price/Grades and an Enroll link.
    The breadcrumb line under the title ("Youth Enrichment / Science &
    Technology") is the authority on audience and category."""
    soup = _fetch(url)
    main = soup.select_one("main") or soup.body
    out: dict = {}

    # breadcrumb: first line after the h1 in the rendered text
    head_text = main.get_text("\n", strip=True)[:400]
    crumb_m = re.search(
        r"\n((?:[A-Z][\w'&,. -]{2,40})(?:\s*/\s*[A-Z][\w'&,. -]{2,40})?)\n", head_text)
    if crumb_m:
        crumb = crumb_m.group(1).strip()
        if ADULT_CRUMB.search(crumb):
            return {"excluded": True, "crumb": crumb}
        for pat, cat in CRUMB_CATEGORY:
            if pat.search(crumb):
                out["category"] = cat
                break

    # the detail page h1 is the canonical course name
    h1 = main.select_one("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
        if 3 < len(title) < 200:
            out["name"] = title

    # description: substantial paragraphs before the section/options block
    paras = []
    for p in main.select("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 60 and not re.match(r"(late registration|to ensure)", t, re.I):
            paras.append(t)
        if sum(len(x) for x in paras) > 900:
            break
    if paras:
        out["description"] = " ".join(paras)[:1200]

    text = _clean(main.get_text("\n", strip=True))

    m = re.search(r"Price:\s*\$([\d,]+(?:\.\d{1,2})?)", text)
    if m:
        out["price"] = float(m.group(1).replace(",", ""))
        out["price_text"] = f"${m.group(1)}"
        out["is_free"] = out["price"] == 0

    m = re.search(r"(Grades?\s+(?:K|\d{1,2})\s*(?:-|–|to)\s*(?:K|\d{1,2}))", text, re.I)
    if not m:
        m = re.search(r"(Ages?\s+\d{1,2}\s*(?:-|–|to)\s*\d{1,2})", text, re.I)
    if m:
        out["age_text"] = m.group(1)
        lo, hi = parse_age_range(m.group(1))
        if lo is not None or hi is not None:
            out["age_min"], out["age_max"] = lo, hi

    m = re.search(r"Starts?\s+\w{3},?\s+([A-Za-z]{3,9}\.?\s+\d{1,2},?\s*\d{4})", text)
    if m:
        d = parse_date(m.group(1))
        if d:
            out["start_date"] = d

    m = re.search(r"(\d{1,2}:\d{2}\s*(?:-|–)\s*\d{1,2}:\d{2}\s*[AP]M)", text)
    if m:
        out["schedule_text"] = m.group(1)

    m = re.search(r"\n([^\n]{6,90},\s*MN\s*\d{5})", text)
    if m:
        out["location"] = m.group(1).strip()

    # status: an add-to-cart link means it's genuinely enrollable
    body_text = text.lower()
    if soup.select_one("a[href*='/cart/add/']"):
        out["registration_status"] = "open"
    elif "waitlist" in body_text:
        out["registration_status"] = "waitlist"
    elif re.search(r"registration (?:is )?closed|no longer available", body_text):
        out["registration_status"] = "closed"
    return out


def parse_generic_detail(url: str) -> dict:
    """Any other site: og:description meta, else the page's substantial
    paragraphs. Conservative — only returns a description."""
    soup = _fetch(url)
    out: dict = {}

    meta = soup.select_one("meta[property='og:description'], meta[name='description']")
    desc = (meta.get("content", "").strip() if meta else "")
    if len(desc) < 80:
        main = soup.select_one("main, article") or soup.body
        paras = [p.get_text(" ", strip=True) for p in main.select("p")]
        paras = [t for t in paras if len(t) > 80][:3]
        joined = " ".join(paras)
        if len(joined) > len(desc):
            desc = joined
    if len(desc) > 60:
        out["description"] = desc[:1200]
    return out


DETAIL_PARSERS = {
    "eleyo": parse_eleyo_arux_detail,
    "arux": parse_eleyo_arux_detail,
}

# fields the detail page is allowed to overwrite
_FIELDS = ("name", "description", "category", "price", "price_text", "is_free",
           "age_text", "age_min", "age_max", "start_date", "schedule_text", "location")


def enrich_source(db: Session, source: Source) -> int:
    """Enrich un-enriched, non-stale activities of one source. Returns count."""
    parser = DETAIL_PARSERS.get(source.platform, parse_generic_detail)
    acts = (db.query(Activity)
            .filter(Activity.source_id == source.id,
                    Activity.stale.is_(False),
                    Activity.enriched_at.is_(None),
                    Activity.signup_url != "")
            .limit(BATCH_LIMIT)
            .all())
    if not acts:
        return 0

    done = 0
    for act in acts:
        try:
            data = parser(act.signup_url)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code in (404, 410):
                # dead link — clear it so the UI falls back to the org catalog
                log.warning("dead signup link (%s) cleared: %s", code, act.signup_url)
                act.signup_url = ""
            act.enriched_at = utcnow()
            continue
        except Exception as e:
            log.warning("enrich failed %s: %s", act.signup_url, e)
            act.enriched_at = utcnow()  # don't retry a broken page every run
            continue

        if data.get("excluded"):
            act.excluded = True
            act.enriched_at = utcnow()
            log.info("excluded non-youth course (%s): %s",
                     data.get("crumb", "?"), act.name[:60])
            continue

        for field in _FIELDS:
            value = data.get(field)
            if value in (None, ""):
                continue
            if field == "description" and len(value) <= len(act.description or ""):
                continue  # never downgrade to a shorter description
            setattr(act, field, value)

        new_status = data.get("registration_status")
        if new_status and new_status != act.registration_status:
            event_type = ("reg_opened"
                          if new_status == "open"
                          and act.registration_status in ("not_yet_open", "unknown")
                          else "status_change")
            db.add(ActivityEvent(activity_id=act.id, event_type=event_type,
                                 old_value=act.registration_status, new_value=new_status))
            act.registration_status = new_status

        act.enriched_at = utcnow()
        done += 1
        if done % 50 == 0:
            db.commit()
            log.info("enriched %d/%d for %s", done, len(acts), source.slug)
        time.sleep(DELAY_S)

    db.commit()
    log.info("enrichment done for %s: %d pages", source.slug, done)
    return done
