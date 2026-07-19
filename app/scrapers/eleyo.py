"""Eleyo/ARUX server-rendered catalog crawler."""
from __future__ import annotations

import re
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from .base import BaseScraper, register, log
from ..services.normalizer import (
    clean_activity_title,
    clean_text,
    extract_age_text,
    extract_price_text,
)

MAX_LISTING_PAGES = 60
EXCLUDE_CATEGORY = re.compile(r"\badult\b|\bsenior\b|driver|fundrais|55\+|21\+", re.I)


def _trim_title_to_slug(name: str, path: str) -> str:
    """Use the human-readable course slug as a safe title boundary.

    ARUX result links sometimes expose status, category, and description as one
    text node.  The final URL segment still contains only the course name.
    When those word sequences agree, preserve the heading's capitalization and
    punctuation but cut it at the end of the slug-derived title.
    """
    segments = [unquote(part) for part in path.split("/") if part]
    slug = segments[-1] if segments else ""
    slug = re.sub(r"[—–-]\d+$", "", slug)
    slug_words = re.findall(r"[a-z0-9]+", re.sub(r"[-_]+", " ", slug).casefold())
    name_matches = list(re.finditer(r"[A-Za-z0-9]+", name))
    name_words = [match.group(0).casefold() for match in name_matches]
    if len(slug_words) < 4 or len(name_words) < len(slug_words):
        return name
    if name_words[:len(slug_words)] != slug_words:
        return name
    return name[:name_matches[len(slug_words) - 1].end()].strip(" -–—:|,")


@register("eleyo")
class EleyoScraper(BaseScraper):
    def scrape(self, source) -> list[dict]:
        root = (source.catalog_url or source.homepage_url).rstrip("/")
        root_host = urlparse(root).netloc.lower()
        results: list[dict] = []
        seen_courses: set[str] = set()
        visited: set[str] = set()
        queue = [root + "/courses", root + "/"]

        while queue and len(visited) < MAX_LISTING_PAGES:
            url = urldefrag(queue.pop(0)).url.rstrip("/") or root
            if url in visited:
                continue
            visited.add(url)
            try:
                soup = self.fetch_html(url)
            except Exception as exc:
                log.warning("eleyo listing failed %s: %s", url, exc)
                continue

            results.extend(self._parse_courses(soup, root, seen_courses))

            for anchor in soup.select("a[href]"):
                full = urldefrag(urljoin(url + "/", anchor.get("href", ""))).url
                parsed = urlparse(full)
                if parsed.netloc.lower() != root_host:
                    continue
                if not (
                    re.search(r"/courses/category/", parsed.path)
                    or re.search(r"/courses/\d+(?:/|$)", parsed.path)
                ):
                    continue
                label = clean_text(anchor.get_text(" ", strip=True), 200)
                if EXCLUDE_CATEGORY.search(f"{full} {label}"):
                    continue
                if full.rstrip("/") not in visited:
                    queue.append(full)
        return results

    @staticmethod
    def _local_card(anchor):
        """Climb only while the parent still represents one course card."""
        card = anchor
        for _ in range(5):
            parent = card.parent
            if parent is None:
                break
            course_links = {
                item.get("href", "")
                for item in parent.select("a[href*='/course/']")
                if item.get("href")
            }
            text_len = len(parent.get_text(" ", strip=True))
            if len(course_links) != 1 or text_len > 1500:
                break
            card = parent
            classes = " ".join(parent.get("class", []))
            if parent.name in {"article", "li"} or re.search(r"card|course|item|result", classes, re.I):
                break
        return card

    def _parse_courses(self, soup, root: str, seen: set[str]) -> list[dict]:
        root_host = urlparse(root).netloc.lower()
        out: list[dict] = []
        for anchor in soup.select("a[href*='/course/']"):
            href = urljoin(root + "/", anchor.get("href", ""))
            parsed = urlparse(href)
            match = re.search(r"/course/(?:[^/?#]+/)?(\d+)(?:/|$)", parsed.path)
            if (
                not match
                or match.group(1) in seen
                or parsed.netloc.lower() != root_host
            ):
                continue
            card = self._local_card(anchor)
            text = clean_text(card.get_text(" ", strip=True), 1500)

            data_description = clean_text(anchor.get("data-description"), 1200)
            heading = card.select_one("h1,h2,h3,h4,h5,[class*='title']")
            name = clean_text(heading.get_text(" ", strip=True), 300) if heading else ""
            if not name:
                segments = [unquote(part) for part in parsed.path.split("/") if part]
                slug_part = segments[-1] if segments else ""
                slug_part = re.sub(r"[—–-]\d+$", "", slug_part)
                if slug_part and not slug_part.isdigit():
                    name = clean_text(re.sub(r"[-_]+", " ", slug_part), 200)
            if not name:
                name = clean_text(anchor.get_text(" ", strip=True), 300)
            name = clean_activity_title(name, data_description, 180)
            name = _trim_title_to_slug(name, parsed.path)
            if len(name) < 3:
                continue
            seen.add(match.group(1))

            date_match = re.search(
                r"([A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:,\s*\d{4})?)\s*"
                r"(?:-|–|—|to)\s*"
                r"([A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:,\s*\d{4})?)",
                text,
            )
            out.append({
                "external_id": f"course-{match.group(1)}",
                "name": name,
                "description": data_description or text,
                "age_text": extract_age_text(text),
                "price_text": extract_price_text(text),
                "start_date": date_match.group(1) if date_match else "",
                "end_date": date_match.group(2) if date_match else "",
                "status_text": text,
                "signup_url": href,
            })
        return out
