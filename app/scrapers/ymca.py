"""YMCA of the North location and program pages."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .base import BaseScraper, register, log
from ..services.normalizer import (
    clean_text,
    extract_age_text,
    extract_price_text,
    stable_external_id,
)

PROGRAM_HINTS = (
    "swim", "sport", "camp", "youth", "child", "kid", "aquatic",
    "enrichment", "school_age", "school-age",
)
MEANINGFUL_HEADING = re.compile(
    r"\b(swim|sport|camp|youth|child|kid|teen|lesson|class|league|clinic|club|program)\b",
    re.I,
)
SKIP_HEADING = re.compile(
    r"^(about|overview|benefits|locations?|hours?|contact|amenities|membership|"
    r"financial assistance|frequently asked questions|related links)$",
    re.I,
)


@register("ymca")
class YMCAScraper(BaseScraper):
    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        soup = self.fetch_html(url)
        root = "https://www.ymcanorth.org"

        program_links = set()
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            label = clean_text(anchor.get_text(" ", strip=True), 160).lower()
            if any(hint in f"{href.lower()} {label}" for hint in PROGRAM_HINTS) and href.count("/") >= 2:
                program_links.add(urljoin(root, href))

        output: list[dict] = []
        seen_ids: set[str] = set()
        for link in sorted(program_links)[:20]:
            try:
                output.extend(self._parse_program_page(source, link, seen_ids))
            except Exception as exc:
                log.warning("ymca page failed %s: %s", link, exc)
        return output

    def _parse_program_page(self, source, url: str, seen_ids: set[str]) -> list[dict]:
        soup = self.fetch_html(url)
        output = []
        for header in soup.select("main h2, main h3, article h2, article h3"):
            name = clean_text(header.get_text(" ", strip=True), 200)
            if not (3 < len(name) < 160) or SKIP_HEADING.fullmatch(name):
                continue

            description_parts: list[str] = []
            for sibling in header.find_next_siblings(limit=5):
                if sibling.name and sibling.name.startswith("h"):
                    break
                text = clean_text(sibling.get_text(" ", strip=True), 600)
                if text:
                    description_parts.append(text)
            description = clean_text(" ".join(description_parts), 1200)
            combined = f"{name} {description}"
            age_text = extract_age_text(combined)
            if not MEANINGFUL_HEADING.search(combined) and not age_text:
                continue

            external_id = stable_external_id(source.slug, url, name)
            if external_id in seen_ids:
                continue
            seen_ids.add(external_id)
            output.append({
                "external_id": external_id,
                "name": name,
                "description": description,
                "age_text": age_text,
                "price_text": extract_price_text(combined),
                "status_text": combined,
                "signup_url": url,
            })
        return output
