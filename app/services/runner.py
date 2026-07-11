"""Scrape orchestration: run scrapers, apply diffs, fire notifications."""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Activity, ActivityEvent, ScrapeLog, Source, utcnow
from ..scrapers import get_scraper
from . import differ, enricher, notifier

log = logging.getLogger("runner")


def scrape_source(db: Session, source: Source) -> ScrapeLog:
    entry = ScrapeLog(source_id=source.id, started_at=utcnow())
    db.add(entry)
    db.commit()

    source.last_scrape_at = utcnow()
    try:
        raw = get_scraper(source.platform).scrape(source)
        new_count, changed_count = differ.apply_scrape(db, source, raw)
        enriched = enricher.enrich_source(db, source)
        if enriched:
            log.info("enriched %d detail pages for %s", enriched, source.slug)
        entry.status = "ok"
        entry.activities_found = len(raw)
        entry.new_count = new_count
        entry.changed_count = changed_count
        source.last_success_at = utcnow()
        source.error_count = 0
        log.info("scraped %s: %d found, %d new, %d changed",
                 source.slug, len(raw), new_count, changed_count)
    except Exception as e:
        entry.status = "error"
        entry.error = f"{e}\n{traceback.format_exc()[-1500:]}"
        source.error_count += 1
        log.error("scrape failed for %s: %s", source.slug, e)
    finally:
        entry.finished_at = utcnow()
        db.commit()
    return entry


def run_all(source_id: int | None = None) -> dict:
    """Scrape all active sources (or one), then evaluate notifications.

    Runs in its own DB session so it works from both the scheduler thread
    and the API's background task.
    """
    db = SessionLocal()
    try:
        started = datetime.utcnow()
        q = db.query(Source).filter(Source.active.is_(True))
        if source_id:
            q = db.query(Source).filter(Source.id == source_id)
        sources = q.all()

        results = [scrape_source(db, s) for s in sources]

        # gather what changed during this run for alerting
        run_events = (db.query(ActivityEvent)
                      .filter(ActivityEvent.created_at >= started,
                              ActivityEvent.notified.is_(False))
                      .all())
        opened = [e.activity for e in run_events
                  if e.event_type == "reg_opened" and not e.activity.excluded]
        new_acts = [e.activity for e in run_events
                    if e.event_type == "first_seen" and not e.activity.excluded]
        soon = differ.find_opening_soon(db, hours=48)

        notifier.alert_reg_opened(db, opened)
        notifier.alert_opening_soon(db, soon)

        summary = "\n".join(
            f"  {r.source.name}: {r.status} "
            f"({r.activities_found} found, {r.new_count} new, {r.changed_count} changed)"
            + (f" — {r.error.splitlines()[0]}" if r.error else "")
            for r in results)
        if source_id is None:  # digest only for full runs
            notifier.send_daily_digest(db, new_acts, opened, soon, summary)

        for e in run_events:
            e.notified = True
        db.commit()

        return {
            "sources_scraped": len(results),
            "ok": sum(1 for r in results if r.status == "ok"),
            "errors": sum(1 for r in results if r.status == "error"),
            "new_activities": len(new_acts),
            "reg_opened": len(opened),
            "opening_soon": len(soon),
        }
    finally:
        db.close()
