"""RevTrak web-store product listings."""
from __future__ import annotations

from urllib.parse import urljoin

from .base import BaseScraper, register
from ..services.normalizer import (
    clean_text,
    extract_age_text,
    extract_price_text,
    safe_http_url,
    stable_external_id,
)


@register("revtrak")
class RevTrakScraper(BaseScraper):
    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        soup = self.fetch_html(url)
        candidates = soup.select(
            "a[href*='revtrak'][href], .product, [class*='product-card'], [class*='product-item']"
        )
        output: dict[str, dict] = {}
        for node in candidates:
            text = clean_text(node.get_text(" ", strip=True), 1000)
            if not (8 <= len(text) <= 800):
                continue
            title_el = node.select_one("[class*='title'],h2,h3,h4")
            name = clean_text(title_el.get_text(" ", strip=True), 200) if title_el else ""
            if not name:
                name = clean_text(text.split("$")[0], 200)
            if len(name) < 3:
                continue
            link = node if node.name == "a" else node.select_one("a[href]")
            signup_url = safe_http_url(urljoin(url, link.get("href", ""))) if link else ""
            provider_id = clean_text(node.get("data-product-id") or node.get("data-id"))
            external_id = (
                f"revtrak-{provider_id}"
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
