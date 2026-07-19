"""Conservative scraper for custom museum, theatre, library, and club sites."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, register, log
from ..services.normalizer import (
    clean_text,
    extract_age_text,
    extract_price_text,
    safe_http_url,
    stable_external_id,
)

PROGRAM_WORD = re.compile(
    r"\b(camp|class|course|lesson|workshop|program|league|clinic|team|club|"
    r"academy|session|training|tryout|storytime|field trip|tournament)\b",
    re.I,
)
YOUTH_HINT = re.compile(
    r"\b(youth|kid|child|children|junior|teen|family|school[- ]?age|preschool|"
    r"pre[- ]?k|kindergarten|grades?\s*(?:k|\d)|ages?\s*\d)\b",
    re.I,
)
ADULT_ONLY = re.compile(r"\b(adult|senior|55\+|60\+|65\+|21\+|18\+)\b", re.I)
GENERIC_LINK = re.compile(
    r"^(?:programs?|activities|classes|camps?|register|registration|learn more|"
    r"view all|read more|details|calendar|events?)$",
    re.I,
)


@register("custom")
class CustomScraper(BaseScraper):
    def scrape(self, source) -> list[dict]:
        url = source.catalog_url or source.homepage_url
        soup = self._get_soup(url)
        self._remove_chrome(soup)

        from ..services import llm_extract
        if llm_extract.enabled():
            try:
                page_text = self._llm_page_text(soup, url)
                items = llm_extract.extract(page_text[:30000], source.name)
                if items:
                    for item in items:
                        item["signup_url"] = safe_http_url(item.get("signup_url")) or url
                        item["external_id"] = item.get("external_id") or stable_external_id(
                            source.slug,
                            item["signup_url"],
                            item.get("name", ""),
                            item.get("start_date", ""),
                        )
                    return items
            except Exception as exc:
                log.warning("LLM extraction failed for %s, using heuristics: %s", source.slug, exc)

        return self._heuristic(soup, url, source)

    def _get_soup(self, url: str) -> BeautifulSoup:
        try:
            soup = self.fetch_html(url)
        except Exception as exc:
            log.info("custom requests fetch failed for %s; trying browser: %s", url, exc)
            html = self.fetch_rendered(url, wait_ms=6000)
            return BeautifulSoup(html, "lxml")

        if len(soup.get_text(strip=True)) < 300:
            html = self.fetch_rendered(url, wait_ms=6000)
            soup = BeautifulSoup(html, "lxml")
        return soup

    @staticmethod
    def _remove_chrome(soup: BeautifulSoup) -> None:
        for node in soup.select(
            "script,style,noscript,svg,nav,header,footer,[role='navigation'],"
            "[aria-hidden='true'],.cookie,.cookies,.newsletter"
        ):
            node.decompose()

    @staticmethod
    def _llm_page_text(soup: BeautifulSoup, base_url: str) -> str:
        body = clean_text(soup.get_text(" ", strip=True), 24000)
        links: list[str] = []
        for anchor in soup.select("a[href]"):
            label = clean_text(anchor.get_text(" ", strip=True), 160)
            if not label or not (PROGRAM_WORD.search(label) or YOUTH_HINT.search(label)):
                continue
            full = safe_http_url(urljoin(base_url, anchor.get("href", "")))
            if full:
                links.append(f"{label} | {full}")
        return body + "\n\nRELEVANT LINKS:\n" + "\n".join(dict.fromkeys(links[:150]))

    @staticmethod
    def _container(element):
        container = element
        for _ in range(4):
            parent = container.parent
            if parent is None:
                break
            text = clean_text(parent.get_text(" ", strip=True))
            program_links = [
                anchor for anchor in parent.select("a[href]")
                if PROGRAM_WORD.search(clean_text(anchor.get_text(" ", strip=True), 160))
            ]
            if len(text) > 1400 or len(program_links) > 3:
                break
            container = parent
        return container

    def _heuristic(self, soup: BeautifulSoup, url: str, source) -> list[dict]:
        output: list[dict] = []
        seen: set[str] = set()
        candidates = soup.select("main h1,main h2,main h3,main h4,main a[href],article h1,article h2,article h3,article h4,article a[href]")
        if not candidates:
            candidates = soup.select("h2,h3,h4,a[href]")

        for element in candidates:
            name = clean_text(element.get_text(" ", strip=True), 200)
            if not (4 < len(name) < 180) or not PROGRAM_WORD.search(name):
                continue
            if GENERIC_LINK.fullmatch(name):
                continue

            container = self._container(element)
            context = clean_text(container.get_text(" ", strip=True), 1200)
            youth = bool(YOUTH_HINT.search(f"{name} {context}"))
            adult = bool(ADULT_ONLY.search(f"{name} {context}"))
            if adult and not youth:
                continue
            if not youth:
                continue

            href = element.get("href", "") if element.name == "a" else ""
            if not href:
                links = container.select("a[href]")
                preferred = next(
                    (
                        anchor for anchor in links
                        if re.search(r"register|enroll|sign up|details|learn more", anchor.get_text(" ", strip=True), re.I)
                    ),
                    links[0] if links else None,
                )
                href = preferred.get("href", "") if preferred else ""
            signup_url = safe_http_url(urljoin(url, href)) if href else url

            age_text = extract_age_text(context)
            price_text = extract_price_text(context)
            external_id = stable_external_id(
                source.slug,
                signup_url,
                name,
                age_text,
            )
            if external_id in seen:
                continue
            seen.add(external_id)

            output.append({
                "external_id": external_id,
                "name": name,
                "description": context,
                "age_text": age_text,
                "price_text": price_text,
                "status_text": context,
                "signup_url": signup_url,
            })
        return output[:120]
