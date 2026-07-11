"""Turn raw scraped dicts into normalized Activity field values.

Scrapers return loose dicts; this module owns all the messy text parsing
(ages, prices, dates, registration status) so scrapers stay simple.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, date

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

STATUS_KEYWORDS = [
    ("waitlist", "waitlist"),
    ("wait list", "waitlist"),
    ("sold out", "closed"),
    ("closed", "closed"),
    ("full", "waitlist"),
    ("register", "open"),
    ("enroll", "open"),
    ("sign up", "open"),
    ("opens", "not_yet_open"),
    ("coming soon", "not_yet_open"),
]


def stable_external_id(*parts: str) -> str:
    """Hash-based fallback id when the provider has no stable id."""
    joined = "||".join(p.strip().lower() for p in parts if p)
    return hashlib.sha1(joined.encode()).hexdigest()[:20]


def parse_age_range(text: str) -> tuple[float | None, float | None]:
    """'ages 5-12' -> (5, 12); '9 mo - 3 yr' -> (0.75, 3); 'grades K-6' -> (5, 12)."""
    if not text:
        return None, None
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.lower())  # "2nd - 6th" -> "2 - 6"

    # grade ranges: K≈5yo, grade n ≈ n+5
    m = re.search(r"grades?\s*(k|\d{1,2})\s*(?:-|–|to|through)\s*(k|\d{1,2})", t)
    if m:
        lo = 5 if m.group(1) == "k" else int(m.group(1)) + 5
        hi = 5 if m.group(2) == "k" else int(m.group(2)) + 6
        return float(lo), float(hi)

    # month-aware ranges e.g. "9 months - 3 years", "6mo-10yr", "9mo+"
    def unit_val(num: str, unit: str) -> float:
        v = float(num)
        return round(v / 12.0, 2) if unit.startswith("m") else v

    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(mo(?:nths?)?|yrs?|years?)?\s*(?:-|–|to|through)\s*"
        r"(\d+(?:\.\d+)?)\s*(mo(?:nths?)?|yrs?|years?)?", t)
    if m:
        u1 = m.group(2) or m.group(4) or "y"
        u2 = m.group(4) or "y"
        return unit_val(m.group(1), u1), unit_val(m.group(3), u2)

    m = re.search(r"(?:ages?\s*)?(\d+(?:\.\d+)?)\s*(mo(?:nths?)?|yrs?|years?)?\s*(?:\+|and up|and older)", t)
    if m:
        return unit_val(m.group(1), m.group(2) or "y"), None

    m = re.search(r"ages?\s*(\d+(?:\.\d+)?)", t)
    if m:
        v = float(m.group(1))
        return v, v
    return None, None


def parse_price(text: str) -> tuple[float | None, bool, bool]:
    """Returns (price, is_free, resident_pricing)."""
    if not text:
        return None, False, False
    t = text.lower()
    is_free = bool(re.search(r"\bfree\b", t)) and "$" not in t
    resident = "resident" in t or "non-resident" in t or "member" in t
    prices = [float(p.replace(",", "")) for p in re.findall(r"\$\s*([\d,]+(?:\.\d{1,2})?)", t)]
    price = min(prices) if prices else (0.0 if is_free else None)
    if price == 0.0:
        is_free = True
    return price, is_free, resident


def parse_date(text: str) -> date | None:
    """Best-effort single-date parse from free text."""
    if not text:
        return None
    t = text.strip().lower()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            pass
    m = re.search(r"([a-z]{3,9})\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?", t)
    if m and m.group(1)[:3] in MONTHS:
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        try:
            return date(year, MONTHS[m.group(1)[:3]], int(m.group(2)))
        except ValueError:
            return None
    return None


def parse_status(text: str) -> str:
    if not text:
        return "unknown"
    t = text.lower()
    for kw, status in STATUS_KEYWORDS:
        if kw in t:
            return status
    return "unknown"


def normalize(raw: dict, default_category: str) -> dict:
    """Map a raw scraper dict onto Activity column values."""
    name = (raw.get("name") or "").strip()[:300]
    age_text = (raw.get("age_text") or "").strip()[:100]
    price_text = (raw.get("price_text") or "").strip()[:200]

    age_min, age_max = raw.get("age_min"), raw.get("age_max")
    if age_min is None and age_max is None:
        age_min, age_max = parse_age_range(age_text or name)

    price, is_free, resident = parse_price(price_text)
    if raw.get("price") is not None:
        price = raw["price"]
        is_free = price == 0

    start = raw.get("start_date")
    if isinstance(start, str):
        start = parse_date(start)
    end = raw.get("end_date")
    if isinstance(end, str):
        end = parse_date(end)

    status = raw.get("registration_status") or parse_status(raw.get("status_text", ""))

    opens_at = raw.get("registration_opens_at")
    if isinstance(opens_at, str):
        d = parse_date(opens_at)
        opens_at = datetime(d.year, d.month, d.day) if d else None

    external_id = raw.get("external_id") or stable_external_id(
        name, age_text, str(start or ""), raw.get("schedule_text", ""))

    return {
        "external_id": str(external_id)[:300],
        "name": name,
        "description": (raw.get("description") or "").strip(),
        "category": (raw.get("category") or default_category).strip().lower(),
        "age_min": age_min,
        "age_max": age_max,
        "age_text": age_text,
        "price": price,
        "price_text": price_text,
        "is_free": is_free,
        "resident_pricing": resident,
        "start_date": start,
        "end_date": end,
        "schedule_text": (raw.get("schedule_text") or "").strip()[:300],
        "location": (raw.get("location") or "").strip()[:300],
        "registration_status": status if status in
            {"not_yet_open", "open", "waitlist", "closed", "unknown"} else "unknown",
        "registration_opens_at": opens_at,
        "signup_url": (raw.get("signup_url") or "").strip()[:600],
    }
