"""APScheduler: daily scrape at AT_SCRAPE_HOUR local time."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import SCRAPE_HOUR, TIMEZONE
from .runner import run_all

log = logging.getLogger("scheduler")
_scheduler: BackgroundScheduler | None = None


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone=TIMEZONE)
    _scheduler.add_job(
        run_all,
        CronTrigger(hour=SCRAPE_HOUR, minute=0),
        id="daily_scrape",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("scheduler started: daily scrape at %02d:00 %s", SCRAPE_HOUR, TIMEZONE)
    return _scheduler


def shutdown():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
