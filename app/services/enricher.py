"""Detail-page enrichment and audience verification.

Listing cards are useful for discovery but are not trusted as the final source
of truth.  This module visits activity-specific pages, upgrades fields, and
permanently hides clearly adult/senior offerings before notifications run.
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
from .normalizer import (
    clean_activity_title,
    extract_age_text,
    extract_price_text,
    parse_age_range,
    parse_date,
    parse_price,
    parse_status,
)

log = logging.getLogger("enricher")

BATCH_LIMIT = 320
DELAY_S = 0.15

_ORDINAL = re.compile(r"(\d)(st|nd|rd|th)\b", re.I)
_ADULT_AUDIENCE = re.compile(
    r"\b(?:adult enrichment|adult education|adults? only|senior(?:s)?|"
    r"older adults?|55\+|60\+|65\+|21\+|18\+|driver'?s? education)\b",
    re.I,
)
_YOUTH_AUDIENCE = re.compile(
    r"\b(?:youth enrichment|youth|children|child|kids?|junior|teen|family|"
    r"preschool|pre[- ]?k|kindergarten|grades?\s*(?:k|\d)|ages?\s*\d)\b",
    re.I,
)

CRUMB_CATEGORY = [
    (re.compile(r"science|tech|academic|stem|math", re.I), "stem / education"),
    (re.compile(r"creative|art|music|theat|dance", re.I), "creative arts"),
    (re.compile(r"health|wellness|sport|athletic|gym|ninja|fitness", re.I), "athletics"),
    (re.compile(r"aquatic|swim", re.I), "aquatics"),
]


def _fetch(url: str) -> BeautifulSoup:
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def _clean(text: str) -> str:
    return _ORDINAL.sub(r"\1", text)


def _breadcrumb_text(soup: BeautifulSoup, main) -> str:
    selectors = (
        "nav[aria-label*='breadcrumb' i]",
        ".breadcrumb",
        "[class*='breadcrumb']",
        "[data-testid*='breadcrumb']",
    )
    pieces: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            text = node.get_text(" / ", strip=True)
            if text and text not in pieces:
                pieces.append(text)
    if pieces:
        return " / ".join(pieces)[:500]

    # ARUX/Eleyo sometimes render the category as a short line directly after
    # the h1 without a breadcrumb class.
    h1 = main.select_one("h1") if main else None
    if h1:
        for sibling in h1.find_all_next(limit=5):
            text = sibling.get_text(" ", strip=True)
            if 3 < len(text) < 140 and "/" in text:
                return text
    return ""


def _audience_exclusion(title: str, breadcrumb: str, intro: str) -> tuple[bool, str]:
    strongest = f"{breadcrumb} {title}".strip()
    if _ADULT_AUDIENCE.search(strongest) and not _YOUTH_AUDIENCE.search(strongest):
        return True, breadcrumb or title

    # Only use body text when it states a clear adult audience near the top;
    # long pages may mention adult supervision inside a youth program.
    intro = intro[:700]
    if _ADULT_AUDIENCE.search(intro) and not _YOUTH_AUDIENCE.search(intro):
        return True, "adult-only page introduction"
    return False, ""


def parse_eleyo_arux_detail(url: str) -> dict:
    """Parse an Eleyo/ARUX course page and verify its audience."""
    soup = _fetch(url)
    main = soup.select_one("main") or soup.body or soup
    out: dict = {}

    h1 = main.select_one("h1")
    raw_title = h1.get_text(" ", strip=True) if h1 else ""
    breadcrumb = _breadcrumb_text(soup, main)
    intro = main.get_text(" ", strip=True)[:1200]
    excluded, reason = _audience_exclusion(raw_title, breadcrumb, intro)
    if excluded:
        return {"excluded": True, "crumb": reason}

    for pattern, category in CRUMB_CATEGORY:
        if pattern.search(breadcrumb):
            out["category"] = category
            break

    paragraphs: list[str] = []
    for paragraph in main.select("p"):
        text = paragraph.get_text(" ", strip=True)
        if len(text) > 60 and not re.match(r"(?:late registration|to ensure)", text, re.I):
            paragraphs.append(text)
        if sum(len(value) for value in paragraphs) > 900:
            break
    if paragraphs:
        out["description"] = " ".join(paragraphs)[:1200]

    title = clean_activity_title(raw_title, out.get("description", ""), 180)
    if 3 < len(title) <= 180:
        out["name"] = title

    text = _clean(main.get_text("\n", strip=True))

    price_text = extract_price_text(text)
    if price_text:
        price, is_free, _resident = parse_price(price_text)
        out["price_text"] = price_text
        out["price"] = price
        out["is_free"] = is_free

    age_text = extract_age_text(text)
    if age_text:
        out["age_text"] = age_text
        low, high = parse_age_range(age_text)
        if low is not None or high is not None:
            out["age_min"], out["age_max"] = low, high

    start_match = re.search(
        r"Starts?\s+\w{3},?\s+([A-Za-z]{3,9}\.?\s+\d{1,2},?\s*\d{4})",
        text,
        re.I,
    )
    if start_match:
        parsed = parse_date(start_match.group(1))
        if parsed:
            out["start_date"] = parsed

    end_match = re.search(
        r"Ends?\s+\w{3},?\s+([A-Za-z]{3,9}\.?\s+\d{1,2},?\s*\d{4})",
        text,
        re.I,
    )
    if end_match:
        parsed = parse_date(end_match.group(1))
        if parsed:
            out["end_date"] = parsed

    schedule_match = re.search(
        r"(\d{1,2}:\d{2}\s*(?:-|–|—)\s*\d{1,2}:\d{2}\s*[AP]M)",
        text,
        re.I,
    )
    if schedule_match:
        out["schedule_text"] = schedule_match.group(1)

    location_match = re.search(r"\n([^\n]{6,90},\s*MN\s*\d{5})", text)
    if location_match:
        out["location"] = location_match.group(1).strip()

    body_text = text.lower()
    if soup.select_one("a[href*='/cart/add/'], button[data-action*='cart']"):
        out["registration_status"] = "open"
    else:
        status = parse_status(body_text)
        if status != "unknown":
            out["registration_status"] = status

    opens_match = re.search(
        r"registration\s+opens?\s+(?:on\s+)?([A-Za-z]{3,9}\.?\s+\d{1,2}(?:,?\s*\d{4})?)",
        text,
        re.I,
    )
    if opens_match:
        parsed = parse_date(opens_match.group(1))
        if parsed:
            from datetime import datetime
            out["registration_opens_at"] = datetime(parsed.year, parsed.month, parsed.day)
            if out.get("registration_status") == "unknown":
                out["registration_status"] = "not_yet_open"
    return out


def parse_generic_detail(url: str) -> dict:
    """Conservatively enrich a non-platform detail page."""
    soup = _fetch(url)
    main = soup.select_one("main, article") or soup.body or soup
    out: dict = {}

    h1 = main.select_one("h1")
    raw_title = h1.get_text(" ", strip=True) if h1 else ""
    breadcrumb = _breadcrumb_text(soup, main)
    intro = main.get_text(" ", strip=True)[:1200]
    excluded, reason = _audience_exclusion(raw_title, breadcrumb, intro)
    if excluded:
        return {"excluded": True, "crumb": reason}

    meta = soup.select_one("meta[property='og:description'], meta[name='description']")
    description = meta.get("content", "").strip() if meta else ""
    if len(description) < 80:
        paragraphs = [p.get_text(" ", strip=True) for p in main.select("p")]
        paragraphs = [text for text in paragraphs if len(text) > 80][:3]
        joined = " ".join(paragraphs)
        if len(joined) > len(description):
            description = joined
    if len(description) > 60:
        out["description"] = description[:1200]

    title = clean_activity_title(raw_title, out.get("description", ""), 180)
    if 3 < len(title) <= 180:
        out["name"] = title

    page_text = main.get_text(" ", strip=True)[:5000]
    age_text = extract_age_text(page_text)
    if age_text:
        out["age_text"] = age_text
        out["age_min"], out["age_max"] = parse_age_range(age_text)
    price_text = extract_price_text(page_text)
    if price_text:
        price, is_free, _resident = parse_price(price_text)
        out.update(price_text=price_text, price=price, is_free=is_free)
    status = parse_status(page_text)
    if status != "unknown":
        out["registration_status"] = status
    return out


DETAIL_PARSERS = {
    "eleyo": parse_eleyo_arux_detail,
    "arux": parse_eleyo_arux_detail,
}

_FIELDS = (
    "name", "description", "category", "price", "price_text", "is_free",
    "age_text", "age_min", "age_max", "start_date", "end_date",
    "schedule_text", "location", "registration_opens_at",
)


def enrich_source(db: Session, source: Source) -> int:
    """Enrich unenriched, visible activities from one source."""
    parser = DETAIL_PARSERS.get(source.platform, parse_generic_detail)
    activities = (
        db.query(Activity)
        .filter(
            Activity.source_id == source.id,
            Activity.stale.is_(False),
            Activity.excluded.is_(False),
            Activity.enriched_at.is_(None),
            Activity.signup_url != "",
        )
        .order_by(Activity.first_seen_at, Activity.id)
        .limit(BATCH_LIMIT)
        .all()
    )
    if not activities:
        return 0

    generic_urls = {
        (source.catalog_url or "").rstrip("/"),
        (source.homepage_url or "").rstrip("/"),
    }
    done = 0
    for activity in activities:
        # A catalog/homepage is not an activity detail page.  Fetching it once
        # per candidate only imports generic metadata and wastes requests.
        if activity.signup_url.rstrip("/") in generic_urls:
            activity.enriched_at = utcnow()
            continue

        try:
            data = parser(activity.signup_url)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if code in (404, 410):
                log.warning("dead signup link (%s) cleared: %s", code, activity.signup_url)
                activity.signup_url = ""
                activity.enriched_at = utcnow()
            elif code in (400, 401, 403):
                # Retrying an intentionally blocked page every morning provides
                # no value; the listing-card data remains available.
                log.warning("detail page unavailable (%s): %s", code, activity.signup_url)
                activity.enriched_at = utcnow()
            else:
                # 429/5xx are transient. Leave enriched_at empty for a later run.
                log.warning("transient enrich HTTP error (%s): %s", code, activity.signup_url)
            continue
        except requests.RequestException as exc:
            log.warning("transient enrich request failure %s: %s", activity.signup_url, exc)
            continue
        except Exception as exc:
            log.warning("enrich parse failed %s: %s", activity.signup_url, exc)
            activity.enriched_at = utcnow()
            continue

        if data.get("excluded"):
            activity.excluded = True
            activity.enriched_at = utcnow()
            log.info(
                "excluded non-youth course (%s): %s",
                data.get("crumb", "?"),
                activity.name[:60],
            )
            continue

        for field in _FIELDS:
            value = data.get(field)
            if value in (None, ""):
                continue
            if field == "description" and len(value) <= len(activity.description or ""):
                continue
            setattr(activity, field, value)

        new_status = data.get("registration_status")
        if new_status and new_status != activity.registration_status:
            event_type = (
                "reg_opened"
                if new_status == "open"
                and activity.registration_status in ("not_yet_open", "unknown")
                else "status_change"
            )
            db.add(ActivityEvent(
                activity_id=activity.id,
                event_type=event_type,
                old_value=activity.registration_status,
                new_value=new_status,
            ))
            activity.registration_status = new_status

        activity.enriched_at = utcnow()
        done += 1
        if done % 50 == 0:
            db.commit()
            log.info("enriched %d/%d for %s", done, len(activities), source.slug)
        time.sleep(DELAY_S)

    db.commit()
    log.info("enrichment done for %s: %d pages", source.slug, done)
    return done
