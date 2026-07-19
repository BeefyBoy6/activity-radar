"""Turn raw scraped dicts into normalized Activity field values.

Scrapers return loose dicts; this module owns text cleanup and parsing so the
platform modules can stay small and the quality gate receives consistent data.
"""
from __future__ import annotations

import hashlib
import html
import re
from datetime import date, datetime
from urllib.parse import urlparse

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_SPACE = re.compile(r"\s+")
_ORDINAL = re.compile(r"(\d)(st|nd|rd|th)\b", re.I)
_STATUS_PREFIX = re.compile(r"^(?:starting soon|waitlist)\s+", re.I)
_ARUX_CATEGORY_SUFFIX = re.compile(
    r"\s+(?:academic|adult lessons|aquatics|career & finance|creative arts|"
    r"events & camps|field trips & non-school days|health and wellness|"
    r"languages & travel|personal interest|pre[- ]?k adventures|"
    r"science & technology|senior program fundraisers|special interest|summer music camps|"
    r"technology|youth lessons)\s*$",
    re.I,
)


def clean_text(value: object, limit: int | None = None) -> str:
    """Decode HTML entities and collapse page whitespace."""
    text = html.unescape(str(value or ""))
    text = _SPACE.sub(" ", text).strip()
    return text[:limit] if limit is not None else text


def clean_activity_title(
    value: object,
    description: object = "",
    limit: int = 180,
) -> str:
    """Return a concise activity title instead of a whole ARUX card.

    Some Eleyo/ARUX result links expose all descendant text as the apparent
    title: status badge + course name + category + description.  The
    description is already stored separately, so use its opening words as a
    reliable boundary, then remove platform-only status/category labels.
    """
    title = clean_text(value)
    desc = clean_text(description)
    if not title:
        return ""

    title = _STATUS_PREFIX.sub("", title).strip()
    trimmed_card_text = False

    if desc and len(title) > 40:
        # Match a progressively shorter prefix so small punctuation/whitespace
        # differences do not prevent us from finding where prose begins.
        prefix = desc[:140]
        words = prefix.split()
        for count in range(len(words), 3, -1):
            marker = " ".join(words[:count])
            if len(marker) < 24:
                break
            index = title.casefold().find(marker.casefold())
            if index >= 5:
                title = title[:index].rstrip(" -–—:|,")
                trimmed_card_text = True
                break

    if trimmed_card_text:
        title = _ARUX_CATEGORY_SUFFIX.sub("", title)
    title = title.strip(" -–—:|,")

    if len(title) > limit:
        shortened = title[: limit + 1]
        boundary = max(
            shortened.rfind(" — "),
            shortened.rfind(" – "),
            shortened.rfind(" | "),
            shortened.rfind(". "),
        )
        if boundary >= 40:
            title = shortened[:boundary]
        else:
            title = shortened.rsplit(" ", 1)[0]
    return clean_text(title)


def stable_external_id(*parts: str) -> str:
    """Hash-based fallback id when the provider has no stable id."""
    joined = "||".join(clean_text(p).lower() for p in parts if clean_text(p))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:20]


def safe_http_url(value: object) -> str:
    """Return an http(s) URL or an empty string.

    Scraped href values can be ``javascript:``, fragments, or malformed page
    text.  Keeping only web URLs also prevents unsafe links reaching the SPA.
    """
    url = clean_text(value, 600)
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def extract_age_text(text: str) -> str:
    """Extract a compact age/grade phrase without swallowing nearby prose."""
    if not text:
        return ""
    t = _ORDINAL.sub(r"\1", clean_text(text))
    patterns = (
        r"\bgrades?\s*(?:pre[- ]?k|k|\d{1,2})\s*(?:-|–|—|to|through)\s*(?:k|\d{1,2})\b",
        r"\bgrades?\s*(?:pre[- ]?k|k|\d{1,2})\b",
        r"\bages?\s*\d+(?:\.\d+)?\s*(?:months?|mos?|years?|yrs?)?\s*"
        r"(?:-|–|—|to|through)\s*\d+(?:\.\d+)?\s*(?:months?|mos?|years?|yrs?)?\b",
        r"\bages?\s*\d+(?:\.\d+)?\s*(?:months?|mos?|years?|yrs?)?\s*"
        r"(?:\+|and up\b|and older\b)",
        r"\b\d+(?:\.\d+)?\s*(?:months?|mos?|years?|yrs?)?\s*"
        r"(?:-|–|—|to|through)\s*\d+(?:\.\d+)?\s*(?:months?|mos?|years?|yrs?)\b",
        r"\b(?:all ages|family|preschool|pre[- ]?k|kindergarten)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, t, re.I)
        if match:
            return clean_text(match.group(0), 100)
    return ""


def extract_price_text(text: str) -> str:
    if not text:
        return ""
    t = clean_text(text)
    if re.search(r"\bfree\b", t, re.I) and "$" not in t:
        return "Free"
    match = re.search(
        r"\$\s*[\d,]+(?:\.\d{1,2})?(?:\s*(?:-|–|to)\s*\$\s*[\d,]+(?:\.\d{1,2})?)?"
        r"(?:\s*/\s*[A-Za-z][A-Za-z -]{0,18})?",
        t,
    )
    return clean_text(match.group(0), 200) if match else ""


def parse_age_range(text: str) -> tuple[float | None, float | None]:
    """Parse common age and grade expressions.

    Examples: ``ages 5-12`` -> ``(5, 12)``; ``9 mo - 3 yr`` ->
    ``(0.75, 3)``; ``grades K-6`` -> approximate school-year ages ``(5, 12)``.
    """
    if not text:
        return None, None
    t = _ORDINAL.sub(r"\1", clean_text(text).lower())

    if re.search(r"\ball ages\b|\bfamily\b", t):
        return 0.0, None

    # grade ranges: K≈5, grade n≈n+5 at the beginning of the school year and
    # n+6 by the end, so use the broader inclusive upper bound.
    m = re.search(
        r"grades?\s*(pre[- ]?k|k|\d{1,2})\s*(?:-|–|—|to|through)\s*(k|\d{1,2})",
        t,
    )
    if m:
        def grade_low(value: str) -> int:
            return 4 if value.startswith("pre") else 5 if value == "k" else int(value) + 5

        def grade_high(value: str) -> int:
            return 5 if value.startswith("pre") else 6 if value == "k" else int(value) + 6

        lo, hi = grade_low(m.group(1)), grade_high(m.group(2))
        if 0 <= lo <= hi <= 21:
            return float(lo), float(hi)

    m = re.search(r"grades?\s*(pre[- ]?k|k|\d{1,2})\b", t)
    if m:
        value = m.group(1)
        if value.startswith("pre"):
            return 4.0, 5.0
        if value == "k":
            return 5.0, 6.0
        grade = int(value)
        if 0 <= grade <= 12:
            return float(grade + 5), float(grade + 6)

    def unit_value(number: str, unit: str) -> float:
        value = float(number)
        return round(value / 12.0, 2) if unit.startswith("m") else value

    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(mo(?:nths?)?|yrs?|years?)?\s*"
        r"(?:-|–|—|to|through)\s*(\d+(?:\.\d+)?)\s*(mo(?:nths?)?|yrs?|years?)?",
        t,
    )
    if m:
        unit1 = m.group(2) or m.group(4) or "years"
        unit2 = m.group(4) or "years"
        lo = unit_value(m.group(1), unit1)
        hi = unit_value(m.group(3), unit2)
        if 0 <= lo <= hi <= 25:
            return lo, hi

    m = re.search(
        r"(?:ages?\s*)?(\d+(?:\.\d+)?)\s*(mo(?:nths?)?|yrs?|years?)?\s*"
        r"(?:\+|and up|and older)",
        t,
    )
    if m:
        lo = unit_value(m.group(1), m.group(2) or "years")
        return (lo, None) if 0 <= lo <= 25 else (None, None)

    m = re.search(r"ages?\s*(\d+(?:\.\d+)?)\b", t)
    if m:
        value = float(m.group(1))
        return (value, value) if 0 <= value <= 25 else (None, None)
    return None, None


def parse_price(text: str) -> tuple[float | None, bool, bool]:
    """Return ``(lowest_price, is_free, has_resident/member_pricing)``."""
    if not text:
        return None, False, False
    t = clean_text(text).lower()
    is_free = bool(re.search(r"\bfree\b", t)) and "$" not in t
    resident = bool(re.search(r"\b(?:non-?resident|resident|non-?member|member)\b", t))
    prices = [float(p.replace(",", "")) for p in re.findall(r"\$\s*([\d,]+(?:\.\d{1,2})?)", t)]
    price = min(prices) if prices else (0.0 if is_free else None)
    if price == 0.0:
        is_free = True
    return price, is_free, resident


def parse_date(text: str) -> date | None:
    """Best-effort single-date parse from free text."""
    if not text:
        return None
    t = clean_text(text).lower()
    for fmt, width in (("%Y-%m-%d", 10), ("%m/%d/%Y", 10), ("%m/%d/%y", 8)):
        try:
            return datetime.strptime(t[:width], fmt).date()
        except ValueError:
            pass

    m = re.search(r"([a-z]{3,9})\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?", t)
    if m and m.group(1)[:3] in MONTHS:
        today = date.today()
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            candidate = date(year, MONTHS[m.group(1)[:3]], int(m.group(2)))
        except ValueError:
            return None
        # Catalog cards often omit the year.  If that month/day is far in the
        # past, it almost certainly refers to the next seasonal occurrence.
        if not m.group(3) and (today - candidate).days > 120:
            candidate = candidate.replace(year=year + 1)
        return candidate
    return None


def parse_status(text: str) -> str:
    """Parse registration state conservatively.

    Generic pages contain the word "register" in navigation and footer text,
    so only actionable/open phrases count as open.
    """
    if not text:
        return "unknown"
    t = clean_text(text).lower()

    if (
        t.strip() in {"closed", "cancelled", "canceled", "sold out"}
        or re.search(
            r"\b(?:sold out|registration (?:is )?closed|enrollment (?:is )?closed|"
            r"registration ended|closed to registration|no longer available|"
            r"(?:class|course|program|session|camp) (?:is )?(?:closed|cancelled|canceled))\b",
            t,
        )
    ):
        return "closed"
    if (
        t.strip() in {"full", "waitlist", "wait list"}
        or re.search(
            r"\b(?:join (?:the )?waitlist|wait\s*list|waitlist|"
            r"(?:class|course|program|session|camp) (?:is )?full|no spots? available)\b",
            t,
        )
    ):
        return "waitlist"
    if re.search(r"\b(?:registration|enrollment)\s+opens?\b|\bopens?\s+(?:on|at|in)\b|\bcoming soon\b|\bnot yet open\b", t):
        return "not_yet_open"
    if re.search(r"\b(?:registration|enrollment)\s+(?:is\s+)?open\b|\bregister now\b|\benroll now\b|\bsign up now\b|\badd to cart\b|\bspots? available\b", t):
        return "open"
    return "unknown"


def normalize(raw: dict, default_category: str) -> dict:
    """Map a raw scraper dict onto Activity column values."""
    description = clean_text(raw.get("description"), 4000)
    name = clean_activity_title(raw.get("name"), description, 180)

    supplied_age = clean_text(raw.get("age_text"), 100)
    age_text = extract_age_text(supplied_age)
    if not age_text and supplied_age:
        supplied_low, supplied_high = parse_age_range(supplied_age)
        if supplied_low is not None or supplied_high is not None:
            age_text = supplied_age
    if not age_text:
        age_text = extract_age_text(f"{name} {description[:1200]}")

    supplied_price = clean_text(raw.get("price_text"), 200)
    price_text = extract_price_text(supplied_price) or supplied_price
    if not price_text:
        price_text = extract_price_text(description[:1200])

    age_min, age_max = raw.get("age_min"), raw.get("age_max")
    if age_min is None and age_max is None:
        age_min, age_max = parse_age_range(age_text or name)

    price, is_free, resident = parse_price(price_text)
    if raw.get("price") is not None:
        try:
            price = float(raw["price"])
        except (TypeError, ValueError):
            price = None
        is_free = price == 0
    if raw.get("is_free") is not None:
        is_free = bool(raw.get("is_free"))
    if raw.get("resident_pricing") is not None:
        resident = bool(raw.get("resident_pricing"))

    start = raw.get("start_date")
    if isinstance(start, str):
        start = parse_date(start)
    end = raw.get("end_date")
    if isinstance(end, str):
        end = parse_date(end)

    status = raw.get("registration_status") or parse_status(
        raw.get("status_text") or f"{name} {description[:1200]}"
    )

    opens_at = raw.get("registration_opens_at")
    if isinstance(opens_at, str):
        parsed = parse_date(opens_at)
        opens_at = datetime(parsed.year, parsed.month, parsed.day) if parsed else None

    signup_url = safe_http_url(raw.get("signup_url"))
    external_id = raw.get("external_id") or stable_external_id(
        signup_url or name,
        name,
        str(start or ""),
        clean_text(raw.get("schedule_text"), 300),
        age_text,
    )

    return {
        "external_id": clean_text(external_id, 300),
        "name": name,
        "description": description,
        "category": clean_text(raw.get("category") or default_category, 60).lower(),
        "age_min": age_min,
        "age_max": age_max,
        "age_text": age_text,
        "price": price,
        "price_text": price_text,
        "is_free": is_free,
        "resident_pricing": resident,
        "start_date": start,
        "end_date": end,
        "schedule_text": clean_text(raw.get("schedule_text"), 300),
        "location": clean_text(raw.get("location"), 300),
        "registration_status": status if status in
            {"not_yet_open", "open", "waitlist", "closed", "unknown"} else "unknown",
        "registration_opens_at": opens_at,
        "signup_url": signup_url,
    }
