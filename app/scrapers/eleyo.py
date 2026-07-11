"""Eleyo-style community-ed catalogs (also the base for ARUX, which uses the
same URL scheme: /courses/category/<id>/... listings and /course/<id>/... items).

Pages are server-rendered, so plain requests + bs4 works. We BFS the listing
pages (categories + subcategories) from <root>/courses and collect course cards.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urldefrag, urljoin

from .base import BaseScraper, register, log

MAX_LISTING_PAGES = 60

# category listings we never crawl — adult/senior audiences, not youth programs
EXCLUDE_CATEGORY = re.compile(r"adult|senior|driver|fundrais|55\+|21\+", re.I)


@register("eleyo")
class EleyoScraper(BaseScraper):

    def scrape(self, source) -> list[dict]:
        root = (source.catalog_url or source.homepage_url).rstrip("/")
        results: list[dict] = []
        seen_courses: set[str] = set()
        visited: set[str] = set()
        # /courses is Eleyo's catalog index; ARUX tenants 404 it but list
        # category links on the tenant homepage, so seed both.
        queue = [root + "/courses", root + "/"]

        while queue and len(visited) < MAX_LISTING_PAGES:
            url = urldefrag(queue.pop(0)).url
            if url in visited:
                continue
            visited.add(url)
            try:
                soup = self.fetch_html(url)
            except Exception as e:
                log.warning("eleyo listing failed %s: %s", url, e)
                continue

            results.extend(self._parse_courses(soup, root, seen_courses))

            # discover category (/courses/category/...) and subcategory
            # (/courses/<id>/...) listing pages on the same tenant
            for a in soup.select("a[href]"):
                full = urljoin(url, a.get("href", ""))
                if not full.startswith(root):
                    continue
                if (re.search(r"/courses/category/", full)
                        or re.search(r"/courses/\d+/", full)):
                    if EXCLUDE_CATEGORY.search(full):
                        continue
                    if urldefrag(full).url not in visited:
                        queue.append(full)
        return results

    def _parse_courses(self, soup, root: str, seen: set[str]) -> list[dict]:
        out = []
        for a in soup.select("a[href*='/course/']"):
            href = urljoin(root + "/", a.get("href", ""))
            m = re.search(r"/course/(?:[\w-]+/)?(\d+)", href)
            if not m or m.group(1) in seen or not href.startswith(root):
                continue
            seen.add(m.group(1))

            card = a
            for _ in range(3):  # climb to the card container for context text
                if card.parent and len(card.parent.get_text(strip=True)) < 600:
                    card = card.parent
                else:
                    break
            text = card.get_text(" ", strip=True)
            # the anchor wraps the whole card (title+grade+description), so
            # derive the name from the URL slug — it's canonical. Fall back to
            # a real heading tag, then truncated anchor text. The detail-page
            # h1 (enricher) supplies exact casing later.
            slug_part = unquote(href.rstrip("/").rsplit("/", 1)[-1])
            slug_part = re.sub(r"[—–-]\d+$", "", slug_part)  # drop "—1" dedupe suffixes
            name = (re.sub(r"[-_]+", " ", slug_part).strip().title()
                    if slug_part and not slug_part.isdigit() else "")
            if not name:
                heading = a.select_one("h1,h2,h3,h4,h5")
                name = heading.get_text(" ", strip=True) if heading else ""
            name = name or a.get_text(" ", strip=True)[:80]
            if len(name) < 3:
                continue

            # ARUX cards carry the full description as a data attribute
            data_desc = (a.get("data-description") or "").strip()

            date_m = re.search(
                r"([A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:,\s*\d{4})?)\s*(?:-|–|to)\s*"
                r"([A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:,\s*\d{4})?)", text)
            out.append({
                "external_id": f"course-{m.group(1)}",
                "name": name[:200],
                "description": (data_desc or text)[:1200],
                "age_text": _first(r"(?:Ages?|Grades?)\s*[:\s]*([\w\s.+-]{1,25})", text),
                "price_text": _first(r"(\$[\d,.]+(?:\s*/\s*\w+)?)", text),
                "start_date": date_m.group(1) if date_m else "",
                "end_date": date_m.group(2) if date_m else "",
                "status_text": text,
                "signup_url": href,
            })
        return out


def _first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""
