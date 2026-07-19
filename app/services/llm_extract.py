"""Optional LLM-based extraction of activity listings from messy page text.

Disabled unless AT_LLM_PROVIDER + AT_LLM_API_KEY are set in .env.
Supports "anthropic" and "gemini". Returns a list of raw activity dicts
in the same shape scrapers produce.
"""
from __future__ import annotations

import json
import logging

import requests

from ..config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER

log = logging.getLogger("llm_extract")

PROMPT = """Extract real, individually registerable youth activities from this webpage text from "{org}".
Return ONLY a JSON array. Each element must use:
{{"name": str, "description": str (1-2 factual sentences), "age_text": str,
"price_text": str, "start_date": "YYYY-MM-DD" or "", "end_date": "YYYY-MM-DD" or "",
"schedule_text": str, "registration_status": one of
"not_yet_open","open","waitlist","closed","unknown",
"registration_opens_at": "YYYY-MM-DD" or "", "signup_url": str or ""}}

Rules:
- Include only a specific camp, class, lesson, league, clinic, club, workshop, or course.
- Exclude landing pages, category names, navigation, calendars, news, memberships, rentals,
  birthday parties, services, and adult/senior offerings.
- Do not invent dates, ages, prices, status, descriptions, or URLs. Use empty strings when absent.
- A generic heading such as "Youth Programs" or "Summer Camps" is not an activity.
- Prefer the activity-specific URL from the RELEVANT LINKS section.
- Return [] when the page does not contain specific registerable listings.

PAGE TEXT:
{text}"""


def enabled() -> bool:
    return bool(LLM_PROVIDER and LLM_API_KEY)


def extract(page_text: str, org_name: str) -> list[dict]:
    prompt = PROMPT.format(org=org_name, text=page_text)
    if LLM_PROVIDER == "anthropic":
        raw = _anthropic(prompt)
    elif LLM_PROVIDER == "gemini":
        raw = _gemini(prompt)
    else:
        return []
    return _parse_json_array(raw)


def _anthropic(prompt: str) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": LLM_MODEL or "claude-haiku-4-5-20251001",
              "max_tokens": 4096,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _gemini(prompt: str) -> str:
    model = LLM_MODEL or "gemini-2.5-flash"
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": LLM_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _parse_json_array(raw: str) -> list[dict]:
    raw = raw.strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        log.warning("LLM returned no JSON array")
        return []
    try:
        items = json.loads(raw[start:end + 1])
        if not isinstance(items, list):
            return []
        cleaned = []
        for item in items[:150]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            cleaned.append(item)
        return cleaned
    except json.JSONDecodeError as e:
        log.warning("LLM JSON parse error: %s", e)
        return []
