"""Notifications: immediate alerts (ntfy + email) and the daily email digest.

Channels are best-effort — if SMTP/ntfy aren't configured we just log.
Mute preferences (categories / sources) are respected here.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

import requests
from sqlalchemy.orm import Session

from ..config import (EMAIL_FROM, EMAIL_TO, NTFY_TOPIC, SMTP_HOST,
                      SMTP_PASSWORD, SMTP_PORT, SMTP_USER)
from ..models import Activity
from . import settings_store

log = logging.getLogger("notifier")


def _muted(db: Session, act: Activity) -> bool:
    s = settings_store.get_all(db)
    return (act.category in s["muted_categories"]
            or act.source_id in s["muted_sources"])


def send_email(subject: str, body: str) -> bool:
    if not (SMTP_HOST and EMAIL_FROM and EMAIL_TO):
        log.info("email not configured; skipping: %s", subject)
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        log.error("email send failed: %s", e)
        return False


def send_ntfy(title: str, message: str, url: str = "") -> bool:
    if not NTFY_TOPIC:
        return False
    try:
        headers = {"Title": title.encode("ascii", "ignore").decode()}
        if url:
            headers["Click"] = url
        response = requests.post(f"https://ntfy.sh/{NTFY_TOPIC}",
                                 data=message.encode(), headers=headers, timeout=15)
        response.raise_for_status()
        return True
    except Exception as e:
        log.error("ntfy send failed: %s", e)
        return False


def _fmt(act: Activity) -> str:
    bits = [act.name, f"[{act.category}]"]
    if act.age_text:
        bits.append(f"ages {act.age_text}")
    if act.price_text:
        bits.append(act.price_text)
    if act.registration_opens_at:
        bits.append(f"reg opens {act.registration_opens_at:%b %d %Y}")
    if act.signup_url:
        bits.append(act.signup_url)
    return " · ".join(bits)



def alert_new(db: Session, acts: list[Activity]):
    settings = settings_store.get_all(db)
    if not settings["notify_new"]:
        return
    acts = [a for a in acts if not _muted(db, a)]
    for act in acts:
        send_ntfy("New youth activity ✨", _fmt(act), act.signup_url)
    if acts:
        send_email(
            f"[Activity Tracker] {len(acts)} new activit{'y' if len(acts) == 1 else 'ies'}",
            "\n\n".join(_fmt(act) for act in acts[:50]),
        )

def alert_reg_opened(db: Session, acts: list[Activity]):
    s = settings_store.get_all(db)
    if not s["notify_reg_opened"]:
        return
    acts = [a for a in acts if not _muted(db, a)]
    for a in acts:
        send_ntfy("Registration OPEN 🟢", _fmt(a), a.signup_url)
    if acts:
        send_email(f"[Activity Tracker] Registration now open: {len(acts)} activit{'y' if len(acts)==1 else 'ies'}",
                   "\n\n".join(_fmt(a) for a in acts))


def alert_opening_soon(db: Session, acts: list[Activity]):
    s = settings_store.get_all(db)
    if not s["notify_opening_soon"]:
        return
    acts = [a for a in acts if not _muted(db, a)]
    for a in acts:
        send_ntfy("Registration opens within 48h ⏰", _fmt(a), a.signup_url)
    if acts:
        send_email(f"[Activity Tracker] Registration opening soon ({len(acts)})",
                   "\n\n".join(_fmt(a) for a in acts))


def send_daily_digest(db: Session, new_acts: list[Activity], opened: list[Activity],
                      soon: list[Activity], scrape_summary: str):
    s = settings_store.get_all(db)
    if not s["daily_digest"]:
        return
    new_acts = [a for a in new_acts if not _muted(db, a)]
    opened = [a for a in opened if not _muted(db, a)]
    soon = [a for a in soon if not _muted(db, a)]
    sections = []
    if opened:
        sections.append("REGISTRATION NOW OPEN\n" + "\n".join(f"  • {_fmt(a)}" for a in opened))
    if soon:
        sections.append("OPENING WITHIN 48 HOURS\n" + "\n".join(f"  • {_fmt(a)}" for a in soon))
    if new_acts:
        sections.append(f"NEW ACTIVITIES ({len(new_acts)})\n" +
                        "\n".join(f"  • {_fmt(a)}" for a in new_acts[:50]))
    if not sections:
        sections.append("No new activities or registration changes today.")
    sections.append("SCRAPE SUMMARY\n" + scrape_summary)
    send_email("[Activity Tracker] Daily digest", "\n\n".join(sections))
