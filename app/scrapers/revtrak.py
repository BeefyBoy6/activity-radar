"""RevTrak web stores (Arden Hills) — server-rendered product listings."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .base import BaseScraper, register
from ..services.normalizer import stable_external_id


@register("revtrak")
class RevTrakScraper(BaseScraper):

    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        soup = self.fetch_html(url)
        out = []
        # RevTrak store items render as product tiles/links
        for a in soup.select("a[href*='revtrak'], .product, [class*='product'], [class*='item']"):
            text = a.get_text(" ", strip=True)
            if len(text) < 8 or len(text) > 500:
                continue
            name = text.split("$")[0].strip()[:120]
            if len(name) < 3:
                continue
            href = a.get("href", "")
            out.append({
                "external_id": stable_external_id(source.slug, name),
                "name": name,
                "description": text[:400],
                "age_text": _search(r"(?:Ages?|Grades?)\s*[:\s]*([\w\s.+-]{1,25})", text),
                "price_text": _search(r"(\$[\d,.]+)", text),
                "status_text": text,
                "signup_url": urljoin(url, href) if href else url,
            })
        # de-dup by external_id (nested elements match multiple selectors)
        uniq = {}
        for r in out:
            uniq.setdefault(r["external_id"], r)
        return list(uniq.values())


def _search(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""
