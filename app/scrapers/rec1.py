"""Rec1 / CivicRec catalogs (secure.rec1.com)."""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, register
from ..services.normalizer import (
    clean_text,
    extract_age_text,
    extract_price_text,
    safe_http_url,
    stable_external_id,
)


@register("rec1")
class Rec1Scraper(BaseScraper):
    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        html = self.fetch_rendered(
            url,
            wait_selector=".activity, .catalog-item, [class*='program']",
            wait_ms=7000,
        )
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(
            ".activity, .catalog-item, .rec1-catalog-item, "
            "[class*='activity-row'], [class*='program-card']"
        )
        output: dict[str, dict] = {}
        for card in cards:
            text = clean_text(card.get_text(" ", strip=True), 1200)
            if len(text) < 10:
                continue
            title_el = card.select_one(
                "[class*='activity-name'],[class*='program-name'],[class*='title'],h1,h2,h3,h4"
            )
            if title_el is None:
                title_el = card.select_one("a[href]")
            name = clean_text(title_el.get_text(" ", strip=True), 200) if title_el else ""
            if len(name) < 3:
                continue

            link = card.select_one("a[href]")
            signup_url = safe_http_url(urljoin(url, link.get("href", ""))) if link else ""
            provider_id = clean_text(
                card.get("data-id")
                or card.get("data-activity-id")
                or (link.get("data-id") if link else "")
            )
            external_id = (
                f"rec1-{provider_id}"
                if provider_id
                else stable_external_id(source.slug, signup_url, name)
            )
            output.setdefault(external_id, {
                "external_id": external_id,
                "name": name,
                "description": text,
                "age_text": extract_age_text(text),
                "price_text": extract_price_text(text),
                "status_text": text,
                "signup_url": signup_url or url,
            })
        return list(output.values())
