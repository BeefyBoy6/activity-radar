"""Generic scraper for custom sites (museums, theatres, libraries, clubs...).

Strategy:
1. Fetch the catalog page (requests first, Playwright fallback for JS apps).
2. Heuristically extract "program-shaped" blocks: headings/links whose text
   mentions youth/camp/class/lesson keywords, plus nearby age/price text.
3. Optionally pass the page text through an LLM extractor (app/services/
   llm_extract.py) when AT_LLM_PROVIDER is configured — much better results
   on messy pages.

This will never be perfect for 20 wildly different sites, but combined with
change-detection it reliably catches *new or changed* offerings, which is
the point of the tracker.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, register, log
from ..services.normalizer import stable_external_id

KEYWORDS = re.compile(
    r"\b(camp|class|classes|lesson|workshop|program|league|clinic|team|"
    r"club|academy|session|registration|register)\b", re.I)
YOUTH_HINT = re.compile(r"\b(youth|kid|child|children|junior|teen|family|"
                        r"grade|ages?\s*\d)\b", re.I)


@register("custom")
class CustomScraper(BaseScraper):

    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        soup = self._get_soup(url)

        # optional LLM path first — best quality when configured
        from ..services import llm_extract
        if llm_extract.enabled():
            try:
                items = llm_extract.extract(soup.get_text(" ", strip=True)[:24000], source.name)
                if items:
                    for it in items:
                        it.setdefault("signup_url", url)
                        it["external_id"] = it.get("external_id") or stable_external_id(
                            source.slug, it.get("name", ""), it.get("age_text", ""))
                    return items
            except Exception as e:
                log.warning("LLM extraction failed for %s, using heuristics: %s", source.slug, e)

        return self._heuristic(soup, url, source)

    def _get_soup(self, url: str) -> BeautifulSoup:
        soup = self.fetch_html(url)
        # if the page body is nearly empty it's probably a JS app
        if len(soup.get_text(strip=True)) < 300:
            html = self.fetch_rendered(url, wait_ms=6000)
            soup = BeautifulSoup(html, "lxml")
        return soup

    def _heuristic(self, soup: BeautifulSoup, url: str, source) -> list[dict]:
        out, seen = [], set()
        candidates = soup.select("h1, h2, h3, h4, a[href]")
        for el in candidates:
            name = el.get_text(" ", strip=True)
            if not (4 < len(name) < 140) or not KEYWORDS.search(name):
                continue

            # pull surrounding context for age/price/status parsing
            container = el
            for _ in range(2):
                if container.parent and len(container.parent.get_text(strip=True)) < 800:
                    container = container.parent
            context = container.get_text(" ", strip=True)[:500]
            if not YOUTH_HINT.search(context) and not YOUTH_HINT.search(name):
                continue

            ext_id = stable_external_id(source.slug, name)
            if ext_id in seen:
                continue
            seen.add(ext_id)

            href = el.get("href", "") if el.name == "a" else ""
            link_el = container.select_one("a[href]") if not href else None
            if link_el:
                href = link_el.get("href", "")

            out.append({
                "external_id": ext_id,
                "name": name,
                "description": context,
                "age_text": _search(r"(?:ages?|grades?)\s*[:\s]*([\w\s.+-]{1,25})", context),
                "price_text": _search(r"(\$[\d,.]+(?:\s*-\s*\$[\d,.]+)?)", context),
                "status_text": context,
                "signup_url": urljoin(url, href) if href else url,
            })
        return out[:120]


def _search(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""
