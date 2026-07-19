"""VS Cloud / WebTrac activity search results."""
from __future__ import annotations

from urllib.parse import urljoin

from .base import BaseScraper, register, log
from ..services.normalizer import (
    clean_text,
    extract_age_text,
    extract_price_text,
    safe_http_url,
    stable_external_id,
)


@register("vscloud")
class VSCloudScraper(BaseScraper):
    def scrape(self, source) -> list[dict]:
        base = source.catalog_url or source.homepage_url
        search_url = base if "search.html" in base else urljoin(base, "search.html?module=AR&display=listview")
        try:
            soup = self.fetch_html(search_url)
        except Exception:
            html = self.fetch_rendered(base, wait_ms=7000)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

        rows = soup.select(
            "tr[id*='arwebsearch'], .result-content, table.websearch_multiline tr, "
            "[class*='activity-result'], [class*='search-result']"
        )
        output: dict[str, dict] = {}
        for row in rows:
            text = clean_text(row.get_text(" ", strip=True), 1400)
            if len(text) < 15:
                continue
            title_el = row.select_one(
                "[class*='activity-name'],[class*='title'],h2,h3,h4,strong,a[href*='detail']"
            )
            if title_el is None:
                title_el = row.select_one("a[href]")
            name = clean_text(title_el.get_text(" ", strip=True), 200) if title_el else ""
            if len(name) < 3:
                continue
            link = row.select_one("a[href]")
            signup_url = safe_http_url(urljoin(search_url, link.get("href", ""))) if link else ""
            provider_id = clean_text(
                row.get("data-id")
                or row.get("data-activity-id")
                or (link.get("data-activity-id") if link else "")
            )
            external_id = (
                f"webtrac-{provider_id}"
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
                "signup_url": signup_url or search_url,
            })
        if not output:
            log.warning("vscloud: no activity rows parsed from %s", search_url)
        return list(output.values())
