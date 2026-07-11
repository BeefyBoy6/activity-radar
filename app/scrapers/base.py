"""Scraper base class and platform registry.

Each platform scraper handles every source on that platform — one Rec1
scraper covers all four Rec1 cities, etc. A scraper's job is only to
return a list of raw dicts; normalization and diffing happen elsewhere.

Raw dict keys (all optional except name):
    name, description, category, age_text, age_min, age_max,
    price, price_text, start_date, end_date, schedule_text, location,
    registration_status, status_text, registration_opens_at,
    signup_url, external_id
"""
from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup

from ..config import REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger("scrapers")

_REGISTRY: dict[str, type["BaseScraper"]] = {}


def register(platform: str):
    def deco(cls):
        _REGISTRY[platform] = cls
        cls.platform = platform
        return cls
    return deco


def get_scraper(platform: str) -> "BaseScraper":
    cls = _REGISTRY.get(platform) or _REGISTRY["custom"]
    return cls()


class BaseScraper:
    platform = "base"

    def scrape(self, source) -> list[dict]:
        """Return raw activity dicts for one source. Raise on hard failure."""
        raise NotImplementedError

    # --- shared fetch helpers -------------------------------------------

    def fetch_html(self, url: str) -> BeautifulSoup:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def fetch_json(self, url: str, **kwargs):
        resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                            **kwargs)
        resp.raise_for_status()
        return resp.json()

    def fetch_rendered(self, url: str, wait_selector: str | None = None,
                       wait_ms: int = 4000) -> str:
        """Load a JS-rendered page with Playwright and return final HTML.

        Playwright is an optional dependency; sources that need it fail
        with a clear message until it's installed.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "This source needs a headless browser. Install with: "
                "pip install playwright && playwright install chromium"
            ) from e

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=wait_ms)
                    except Exception:
                        log.warning("wait_for_selector(%s) timed out on %s", wait_selector, url)
                else:
                    page.wait_for_timeout(wait_ms)
                return page.content()
            finally:
                browser.close()
