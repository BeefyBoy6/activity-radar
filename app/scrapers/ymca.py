"""YMCA of the North location pages (ymcanorth.org) — server-rendered Drupal.

Scrapes the location page plus its linked program pages (swim lessons,
youth sports, camps) one level deep.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .base import BaseScraper, register, log
from ..services.normalizer import stable_external_id

PROGRAM_HINTS = ("swim", "sport", "camp", "youth", "child", "kid", "aquatic",
                 "enrichment", "school_age", "school-age")


@register("ymca")
class YMCAScraper(BaseScraper):

    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        soup = self.fetch_html(url)
        root = "https://www.ymcanorth.org"

        program_links = set()
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if any(h in href.lower() for h in PROGRAM_HINTS) and href.count("/") >= 2:
                program_links.add(urljoin(root, href))

        out = []
        seen_ids: set[str] = set()
        for link in sorted(program_links)[:15]:
            try:
                out.extend(self._parse_program_page(source, link, seen_ids))
            except Exception as e:
                log.warning("ymca page failed %s: %s", link, e)
        return out

    def _parse_program_page(self, source, url: str, seen_ids: set[str]) -> list[dict]:
        soup = self.fetch_html(url)
        out = []
        # program blocks are usually h2/h3 sections with description text
        for header in soup.select("main h2, main h3, article h2, article h3"):
            name = header.get_text(" ", strip=True)
            if not (3 < len(name) < 120):
                continue
            desc_parts = []
            for sib in header.find_next_siblings(limit=3):
                if sib.name and sib.name.startswith("h"):
                    break
                desc_parts.append(sib.get_text(" ", strip=True))
            desc = " ".join(p for p in desc_parts if p)[:400]
            ext_id = stable_external_id(source.slug, url, name)
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)
            text = f"{name} {desc}"
            out.append({
                "external_id": ext_id,
                "name": name,
                "description": desc,
                "age_text": _search(r"(?:ages?|grades?)\s*[:\s]*([\w\s.+-]{1,25})", text),
                "price_text": _search(r"(\$[\d,.]+)", text),
                "status_text": text,
                "signup_url": url,
            })
        return out


def _search(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""
