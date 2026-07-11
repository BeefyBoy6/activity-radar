"""Upsert scraped activities and record change events.

This is where "new today", registration-open transitions, and signup
history come from.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Activity, ActivityEvent, Source, utcnow
from .normalizer import normalize


def apply_scrape(db: Session, source: Source, raw_items: list[dict]) -> tuple[int, int]:
    """Returns (new_count, changed_count)."""
    new_count = changed_count = 0
    now = utcnow()
    seen_ids: set[str] = set()

    for raw in raw_items:
        data = normalize(raw, source.default_category)
        if not data["name"] or data["external_id"] in seen_ids:
            continue
        seen_ids.add(data["external_id"])

        existing = (db.query(Activity)
                    .filter_by(source_id=source.id, external_id=data["external_id"])
                    .one_or_none())
        if existing is not None and existing.excluded:
            # known non-youth course: keep it marked seen, change nothing else
            existing.last_seen_at = now
            existing.stale = False
            continue

        if existing is None:
            act = Activity(source_id=source.id, **data,
                           first_seen_at=now, last_seen_at=now, last_scraped_at=now)
            db.add(act)
            db.flush()
            db.add(ActivityEvent(activity_id=act.id, event_type="first_seen",
                                 new_value=data["registration_status"]))
            new_count += 1
        else:
            old_status = existing.registration_status
            new_status = data["registration_status"]

            # keep a known status rather than downgrading to unknown
            if new_status == "unknown" and old_status != "unknown":
                data["registration_status"] = old_status
                new_status = old_status

            if old_status != new_status:
                event_type = ("reg_opened"
                              if new_status == "open" and old_status in ("not_yet_open", "unknown")
                              else "status_change")
                db.add(ActivityEvent(activity_id=existing.id, event_type=event_type,
                                     old_value=old_status, new_value=new_status))
                changed_count += 1
                existing.enriched_at = None  # re-check the detail page on change

            for key, value in data.items():
                # listing cards carry less detail than enriched records:
                # never blank out a known value or shorten the description
                if key == "description" and len(value or "") < len(existing.description or ""):
                    continue
                if value in (None, "") and getattr(existing, key) not in (None, ""):
                    continue
                if key == "is_free" and value is False and data.get("price") is None:
                    continue  # card had no price signal; keep the enriched flag
                setattr(existing, key, value)
            existing.last_seen_at = now
            existing.last_scraped_at = now
            existing.stale = False

    # mark activities missing from this scrape as stale (don't delete history)
    if seen_ids:
        (db.query(Activity)
         .filter(Activity.source_id == source.id,
                 Activity.external_id.notin_(seen_ids),
                 Activity.stale.is_(False))
         .update({"stale": True}, synchronize_session=False))

    db.commit()
    return new_count, changed_count


def find_opening_soon(db: Session, hours: int = 48) -> list[Activity]:
    """Activities whose registration opens within `hours` and haven't been
    notified about it yet."""
    now = datetime.utcnow()
    horizon = now + timedelta(hours=hours)
    candidates = (db.query(Activity)
                  .filter(Activity.registration_opens_at.isnot(None),
                          Activity.registration_opens_at > now,
                          Activity.registration_opens_at <= horizon,
                          Activity.stale.is_(False),
                          Activity.excluded.is_(False))
                  .all())
    out = []
    for act in candidates:
        already = any(e.event_type == "reg_opening_soon" for e in act.events)
        if not already:
            db.add(ActivityEvent(activity_id=act.id, event_type="reg_opening_soon",
                                 new_value=str(act.registration_opens_at)))
            out.append(act)
    db.commit()
    return out
