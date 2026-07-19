"""Quality gate for scraped activity candidates.

Scrapers intentionally return loose data because provider sites vary wildly.
This module is the final checkpoint before a candidate is allowed into the
activity database.  It favors false negatives over false positives: a missed
listing can be recovered on the next scrape, while noisy navigation/rental
cards create misleading alerts and pollute history.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

from .normalizer import parse_age_range


_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[A-Za-z]{2,}")

# Titles that are usually menus, landing-page links, or calls to action rather
# than individual programs.  Exact/near-exact matching avoids rejecting a real
# title such as "Summer Camp: Planetarium Explorers".
_GENERIC_TITLE = re.compile(
    r"^(?:"
    r"programs?|activities|classes|camps?|lessons?|leagues?|clinics?|workshops?|"
    r"youth programs?|children'?s programs?|family programs?|"
    r"registration|register(?: now)?|enroll(?: now)?|sign up|"
    r"view all|view details|learn more|read more|find a program|browse programs?|"
    r"upcoming events?|event calendar|calendar|schedule|catalog|home"
    r")\s*[›»→-]*$",
    re.I,
)

_UI_OR_SITE_CHROME = re.compile(
    r"\b(?:cookie|privacy policy|terms of use|accessibility|skip to content|"
    r"newsletter|subscribe|contact us|about us|site map|search results?|"
    r"shopping cart|my account|log ?in|sign ?in|donate|careers?|employment|"
    r"press release|board meeting|request a brochure)\b",
    re.I,
)

_NON_ACTIVITY = re.compile(
    r"\b(?:facility|room|shelter|field|court|equipment|party)\s+rentals?\b|"
    r"\brent(?:al|ing)?\b|\bbirthday part(?:y|ies)(?:\s+packages?)?\b|\bgift cards?\b|"
    r"\bseason pass(?:es)?\b|\b(?:\d+[- ]?)?punch pass(?:es)?\b|\bmulti[- ]visit pass(?:es)?\b|\bdonations?\b|"
    r"\bearly childhood screening\b|\bchild care registration forms?\b|"
    r"\brefund policy\b|\bfinancial assistance\b|\bscholarships?\b",
    re.I,
)

_LIKELY_ADULT_TITLE = re.compile(
    r"^(?:disco splash!?|swimnastics|h2o cardio|water exercise(?:\s+\d+[- ]?punch pass)?)$",
    re.I,
)

_SERVICE_TITLE = re.compile(r"^(?:let['’]s do lunch)(?:\s+@.*)?$", re.I)

_ADULT = re.compile(
    r"\b(?:adult(?:s| only)?|senior(?:s)?|older adults?|55\+|60\+|65\+|21\+|"
    r"18\+|driver'?s? education|wine tasting|casino trip)\b",
    re.I,
)

_YOUTH = re.compile(
    r"\b(?:youth|kid(?:s)?|child(?:ren)?|junior|teen|family|school[- ]?age|"
    r"preschool|pre[- ]?k|kindergarten|elementary|middle school|high school|grades?\s*(?:k|\d)|ages?\s*\d|"
    r"boys?\s*&?\s*girls?|little learners?)\b",
    re.I,
)

_ACTIVITY = re.compile(
    r"\b(?:camp|class|course|lesson|workshop|program|league|clinic|club|team|"
    r"academy|session|tournament|practice|training|tryout|storytime|chess|"
    r"soccer|football|basketball|baseball|softball|hockey|lacrosse|volleyball|"
    r"tennis|golf|swim|swimming|aquatics|gymnastics|dance|theatre|theater|"
    r"music|art|painting|sewing|coding|robot|science|nature|maker|field trip)\b",
    re.I,
)

_STATUS_SIGNAL = re.compile(
    r"\b(?:register|enroll|sign up|waitlist|sold out|registration|spots? available|"
    r"opens?\s+(?:on|at|in)|closed|full)\b",
    re.I,
)


@dataclass(frozen=True)
class QualityDecision:
    accepted: bool
    score: int
    reasons: tuple[str, ...]

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons)


def _clean(value: object) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()


def _is_detail_url(url: str, source) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    generic = {
        _clean(getattr(source, "catalog_url", "")).rstrip("/"),
        _clean(getattr(source, "homepage_url", "")).rstrip("/"),
    }
    if url.rstrip("/") in generic:
        return False

    # A URL with a meaningful path/query is generally activity-specific.  Hash
    # routes are common on registration SPAs, so include the fragment.
    specificity = len([p for p in parsed.path.split("/") if p])
    return specificity >= 2 or bool(parsed.query) or len(parsed.fragment) > 10


def evaluate(data: dict, source) -> QualityDecision:
    """Score one normalized candidate and decide whether it is meaningful.

    Structured platform listings get a slightly lower threshold than generic
    museum/theatre pages because their detail URLs and card markup are stronger
    evidence.  Hard rejection rules always win.
    """
    name = _clean(data.get("name"))
    description = _clean(data.get("description"))
    age_text = _clean(data.get("age_text"))
    price_text = _clean(data.get("price_text"))
    schedule = _clean(data.get("schedule_text"))
    url = _clean(data.get("signup_url"))
    combined = " ".join(x for x in (name, age_text, description[:1000]) if x)

    hard: list[str] = []
    if len(name) < 5:
        hard.append("title too short")
    if len(name) > 220:
        hard.append("title too long")
    if len(_WORD.findall(name)) < 1:
        hard.append("title has no meaningful words")
    if "\n" in name or "\r" in name:
        hard.append("title contains page text")
    if _GENERIC_TITLE.fullmatch(name):
        hard.append("generic landing-page title")
    if _UI_OR_SITE_CHROME.search(name):
        hard.append("site navigation or boilerplate")
    if _NON_ACTIVITY.search(name) or _SERVICE_TITLE.fullmatch(name):
        hard.append("service, rental, or non-program listing")
    if _LIKELY_ADULT_TITLE.fullmatch(name) and not _YOUTH.search(name):
        hard.append("likely adult fitness offering")

    title_youth_signal = bool(_YOUTH.search(name))
    youth_signal = bool(_YOUTH.search(combined))
    age_min = data.get("age_min")
    age_max = data.get("age_max")
    if age_min is None and age_max is None and age_text:
        age_min, age_max = parse_age_range(age_text)
    child_age_signal = (
        (age_min is not None and 0 <= float(age_min) <= 17)
        or (age_max is not None and 0 <= float(age_max) <= 18)
    )

    if _ADULT.search(name) and not title_youth_signal:
        hard.append("adult-only title")
    elif _ADULT.search(combined) and not (youth_signal or child_age_signal):
        hard.append("adult-only audience")

    if hard:
        return QualityDecision(False, -10, tuple(dict.fromkeys(hard)))

    score = 1  # a non-generic, human-readable title
    reasons: list[str] = []

    if _ACTIVITY.search(name):
        score += 2
    else:
        reasons.append("title lacks a clear activity term")

    if youth_signal:
        score += 2
    if child_age_signal:
        score += 2
    if _is_detail_url(url, source):
        score += 2
    else:
        reasons.append("no activity-specific signup link")
    if data.get("start_date") or data.get("end_date") or schedule:
        score += 2
    else:
        reasons.append("no date or schedule")
    if data.get("price") is not None or data.get("is_free") or price_text:
        score += 1
    if data.get("registration_status") not in (None, "", "unknown"):
        score += 1
    elif _STATUS_SIGNAL.search(combined):
        score += 1
    if len(description) >= 60:
        score += 1

    platform = _clean(getattr(source, "platform", "custom")).lower()
    threshold = 6 if platform in {"custom", "ymca"} else 4

    # Generic/custom pages without youth evidence are the main source of noise.
    if platform in {"custom", "ymca"} and not (youth_signal or child_age_signal):
        score -= 2
        reasons.append("no youth audience evidence")

    accepted = score >= threshold
    if not accepted and not reasons:
        reasons.append("insufficient program evidence")
    return QualityDecision(accepted, score, tuple(dict.fromkeys(reasons)))
