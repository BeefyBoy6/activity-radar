"""Rec1 / CivicRec catalogs (secure.rec1.com/MN/<city>/catalog).

Covers: Shoreview CC, Little Canada, New Brighton, Mounds View CC.
The catalog is JS-rendered, so this uses Playwright.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .base import BaseScraper, register
from ..services.normalizer import stable_external_id


@register("rec1")
class Rec1Scraper(BaseScraper):

    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        html = self.fetch_rendered(url, wait_selector=".activity, .catalog-item, [class*='program']")
        soup = BeautifulSoup(html, "lxml")

        cards = soup.select(
            ".activity, .catalog-item, .rec1-catalog-item, "
            "[class*='activity-row'], [class*='program-card']")
        out = []
        for card in cards:
            text = card.get_text(" ", strip=True)
            if len(text) < 10:
                continue
            title_el = card.select_one("h1,h2,h3,h4,a,strong")
            name = title_el.get_text(" ", strip=True) if title_el else text[:80]
            link = card.select_one("a[href]")
            out.append({
                "external_id": stable_external_id(source.slug, name, text[:120]),
                "name": name,
                "description": text[:400],
                "age_text": _search(r"(?:Ages?|Grades?)\s*[:\s]*([\w\s.+-]{1,25})", text),
                "price_text": _search(r"(\$[\d,.]+)", text),
                "status_text": text,
                "signup_url": (link["href"] if link and link["href"].startswith("http")
                               else url),
            })
        return out


def _search(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""
