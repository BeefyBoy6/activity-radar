"""Dash by DaySmart (Roseville Parks & Rec).

apps.daysmartrecreation.com is a JS single-page app; needs Playwright.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .base import BaseScraper, register
from ..services.normalizer import stable_external_id

DEFAULT_URL = "https://apps.daysmartrecreation.com/dash/x/#/online/roseville/programs"


@register("dash")
class DashScraper(BaseScraper):

    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or DEFAULT_URL
        html = self.fetch_rendered(url, wait_selector="[class*='program'], [class*='card']",
                                   wait_ms=8000)
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("[class*='program-card'], [class*='event-card'], "
                            "[class*='card']:has(a)")
        out = []
        for card in cards:
            text = card.get_text(" ", strip=True)
            if len(text) < 15:
                continue
            title_el = card.select_one("h1,h2,h3,h4,[class*='title'],a")
            name = title_el.get_text(" ", strip=True) if title_el else text[:80]
            if len(name) < 3:
                continue
            out.append({
                "external_id": stable_external_id(source.slug, name, text[:120]),
                "name": name,
                "description": text[:400],
                "age_text": _search(r"(?:Ages?|Grades?)\s*[:\s]*([\w\s.+-]{1,25})", text),
                "price_text": _search(r"(\$[\d,.]+)", text),
                "status_text": text,
                "signup_url": url,
            })
        return out


def _search(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""
