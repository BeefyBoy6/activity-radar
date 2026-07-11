"""VS Cloud / WebTrac (St. Paul Parks & Rec) — server-rendered search results.

WebTrac exposes a plain GET search: .../webtrac/web/search.html?module=AR
(Activity Registration). Results are HTML tables we can parse directly.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .base import BaseScraper, register, log
from ..services.normalizer import stable_external_id


@register("vscloud")
class VSCloudScraper(BaseScraper):

    def scrape(self, source) -> list[dict]:
        base = source.catalog_url or source.homepage_url
        search_url = base
        if "search.html" not in base:
            search_url = urljoin(base, "search.html?module=AR&display=listview")
        try:
            soup = self.fetch_html(search_url)
        except Exception:
            # some tenants block direct search; fall back to rendered splash
            html = self.fetch_rendered(base, wait_ms=6000)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

        out = []
        rows = soup.select("tr[id*='arwebsearch'], .result-content, "
                           "table.websearch_multiline tr, [class*='result']")
        for row in rows:
            text = row.get_text(" ", strip=True)
            if len(text) < 15:
                continue
            title_el = row.select_one("a, strong, [class*='title'], td")
            name = title_el.get_text(" ", strip=True)[:120] if title_el else text[:80]
            if len(name) < 3:
                continue
            link = row.select_one("a[href]")
            href = link.get("href", "") if link else ""
            out.append({
                "external_id": stable_external_id(source.slug, name, text[:120]),
                "name": name,
                "description": text[:400],
                "age_text": _search(r"(?:Ages?|Grades?)\s*[:\s]*([\w\s.+-]{1,25})", text),
                "price_text": _search(r"(\$[\d,.]+)", text),
                "status_text": text,
                "signup_url": urljoin(search_url, href) if href else search_url,
            })
        if not out:
            log.warning("vscloud: no rows parsed from %s", search_url)
        uniq = {}
        for r in out:
            uniq.setdefault(r["external_id"], r)
        return list(uniq.values())


def _search(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""
