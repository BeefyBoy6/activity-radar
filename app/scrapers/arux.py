"""ARUX registration portals (roseville.arux.app, moundsview.arux.app).

ARUX tenants serve server-rendered catalogs with the same URL scheme Eleyo
uses (/courses/category/... listings, /course/<id>/... items), so we reuse
the Eleyo BFS parser and only fall back to Playwright if that finds nothing
(some tenants render client-side).
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from .base import register, log
from .eleyo import EleyoScraper


@register("arux")
class AruxScraper(EleyoScraper):

    def scrape(self, source) -> list[dict]:
        results = super().scrape(source)
        if results:
            return results

        log.info("arux %s: server-side parse found nothing, trying rendered page",
                 source.slug)
        root = (source.catalog_url or source.homepage_url).rstrip("/")
        html = self.fetch_rendered(root + "/courses", wait_ms=8000)
        soup = BeautifulSoup(html, "lxml")
        return self._parse_courses(soup, root, set())
