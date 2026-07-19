"""Scrape orchestration: run scrapers, apply quality/diffs, and notify."""
from __future__ import annotations

import logging
from threading import Lock
import traceback

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ActivityEvent, ScrapeLog, Source, utcnow
from ..scrapers import get_scraper
from . import differ, enricher, notifier

log = logging.getLogger("runner")
_RUN_LOCK = Lock()


def is_running() -> bool:
    return _RUN_LOCK.locked()


def scrape_source(db: Session, source: Source) -> ScrapeLog:
    entry = ScrapeLog(source_id=source.id, started_at=utcnow())
    db.add(entry)
    db.commit()

    source.last_scrape_at = utcnow()
    try:
        raw = get_scraper(source.platform).scrape(source)
        result = differ.apply_scrape(db, source, raw)
        enriched = enricher.enrich_source(db, source)
        if enriched:
            log.info("enriched %d detail pages for %s", enriched, source.slug)

        entry.status = "warning" if result.staling_skipped else "ok"
        entry.activities_found = result.accepted_count
        entry.new_count = result.new_count
        entry.changed_count = result.changed_count
        entry.rejected_count = result.rejected_count
        entry.rejection_summary = result.rejection_summary
        entry.staling_skipped = result.staling_skipped
        source.last_success_at = utcnow()
        source.error_count = 0

        log.info(
            "scraped %s: %d raw, %d accepted, %d rejected, %d duplicates, "
            "%d new, %d changed, %d stale%s",
            source.slug,
            result.raw_count,
            result.accepted_count,
            result.rejected_count,
            result.duplicate_count,
            result.new_count,
            result.changed_count,
            result.stale_marked,
            " (stale update skipped for safety)" if result.staling_skipped else "",
        )
        if result.rejection_summary:
            log.info("rejections for %s: %s", source.slug, result.rejection_summary)
    except Exception as exc:
        entry.status = "error"
        entry.error = f"{exc}\n{traceback.format_exc()[-2500:]}"
        source.error_count += 1
        log.error("scrape failed for %s: %s", source.slug, exc)
    finally:
        entry.finished_at = utcnow()
        db.commit()
    return entry


def run_all(source_id: int | None = None) -> dict:
    """Scrape active sources (or one source) in an isolated DB session.

    A process-wide lock prevents a manual scrape from overlapping the scheduler
    or another click, which otherwise causes duplicate notifications and SQLite
    lock contention.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        log.warning("scrape request ignored because another scrape is running")
        return {"started": False, "busy": True}

    db = SessionLocal()
    try:
        started = utcnow()
        if source_id is None:
            sources = db.query(Source).filter(Source.active.is_(True)).all()
        else:
            source = db.get(Source, source_id)
            sources = [source] if source is not None else []

        results = [scrape_source(db, source) for source in sources]

        run_events = (
            db.query(ActivityEvent)
            .filter(
                ActivityEvent.created_at >= started,
                ActivityEvent.notified.is_(False),
            )
            .all()
        )
        opened = [
            event.activity for event in run_events
            if event.event_type == "reg_opened" and not event.activity.excluded
        ]
        new_acts = [
            event.activity for event in run_events
            if event.event_type == "first_seen" and not event.activity.excluded
        ]
        soon = differ.find_opening_soon(db, hours=48)

        notifier.alert_new(db, new_acts)
        notifier.alert_reg_opened(db, opened)
        notifier.alert_opening_soon(db, soon)

        summary = "\n".join(
            f"  {row.source.name}: {row.status} "
            f"({row.activities_found} accepted, {row.rejected_count} rejected, "
            f"{row.new_count} new, {row.changed_count} changed)"
            + (f" — {row.error.splitlines()[0]}" if row.error else "")
            + (" — stale update skipped" if row.staling_skipped else "")
            for row in results
        )
        if source_id is None:
            notifier.send_daily_digest(db, new_acts, opened, soon, summary)

        for event in run_events:
            event.notified = True
        db.commit()

        return {
            "started": True,
            "sources_scraped": len(results),
            "ok": sum(1 for row in results if row.status == "ok"),
            "warnings": sum(1 for row in results if row.status == "warning"),
            "errors": sum(1 for row in results if row.status == "error"),
            "accepted_activities": sum(row.activities_found for row in results),
            "rejected_candidates": sum(row.rejected_count for row in results),
            "new_activities": len(new_acts),
            "reg_opened": len(opened),
            "opening_soon": len(soon),
        }
    finally:
        db.close()
        _RUN_LOCK.release()
