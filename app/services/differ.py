"""Upsert scraped activities, reject noise, and record meaningful changes."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config import TIMEZONE
from ..models import Activity, ActivityEvent, Source, utcnow
from .normalizer import normalize
from .quality import evaluate


@dataclass
class ApplyResult:
    raw_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    new_count: int = 0
    changed_count: int = 0
    stale_marked: int = 0
    staling_skipped: bool = False
    rejection_reasons: Counter[str] = field(default_factory=Counter)

    @property
    def rejection_summary(self) -> str:
        if not self.rejection_reasons:
            return ""
        return "; ".join(
            f"{reason} ({count})"
            for reason, count in self.rejection_reasons.most_common(6)
        )[:1500]


_MEANINGFUL_FIELDS = (
    "price", "price_text", "is_free", "start_date", "end_date",
    "registration_opens_at", "schedule_text", "location", "signup_url",
)


def _merged_for_quality(data: dict, existing: Activity | None) -> dict:
    """Use known details when a listing card is temporarily sparse."""
    if existing is None:
        return data
    merged = dict(data)
    for key in (
        "description", "age_min", "age_max", "age_text", "price", "price_text",
        "is_free", "start_date", "end_date", "schedule_text", "location",
        "registration_status", "registration_opens_at", "signup_url",
    ):
        value = merged.get(key)
        if value in (None, "", False) and getattr(existing, key) not in (None, "", False):
            merged[key] = getattr(existing, key)
    return merged


def apply_scrape(db: Session, source: Source, raw_items: list[dict]) -> ApplyResult:
    """Normalize and upsert one source's scrape output.

    Candidates that do not look like real youth activities are rejected before
    they can create records or notifications.  Stale marking is guarded against
    parser collapse: an unexpectedly tiny or mostly-rejected scrape preserves
    prior records and is surfaced as a warning in the scrape log.
    """
    result = ApplyResult(raw_count=len(raw_items))
    now = utcnow()
    seen_ids: set[str] = set()
    previous_active = (
        db.query(Activity)
        .filter(Activity.source_id == source.id, Activity.stale.is_(False))
        .count()
    )

    for raw in raw_items:
        try:
            data = normalize(raw, source.default_category)
        except Exception as exc:
            result.rejected_count += 1
            result.rejection_reasons[f"normalization error: {type(exc).__name__}"] += 1
            continue

        if not data["name"] or not data["external_id"]:
            result.rejected_count += 1
            result.rejection_reasons["missing title or stable id"] += 1
            continue
        if data["external_id"] in seen_ids:
            result.duplicate_count += 1
            continue

        existing = (
            db.query(Activity)
            .filter_by(source_id=source.id, external_id=data["external_id"])
            .one_or_none()
        )

        # Excluded adult/senior records remain excluded but are still marked as
        # seen so their historical state is not mistaken for a parser failure.
        if existing is not None and existing.excluded:
            seen_ids.add(data["external_id"])
            existing.last_seen_at = now
            existing.last_scraped_at = now
            existing.stale = False
            result.accepted_count += 1
            continue

        decision = evaluate(_merged_for_quality(data, existing), source)
        if not decision.accepted:
            result.rejected_count += 1
            for reason in decision.reasons or ("insufficient program evidence",):
                result.rejection_reasons[reason] += 1
            continue

        seen_ids.add(data["external_id"])
        result.accepted_count += 1

        if existing is None:
            act = Activity(
                source_id=source.id,
                **data,
                first_seen_at=now,
                last_seen_at=now,
                last_scraped_at=now,
            )
            db.add(act)
            db.flush()
            db.add(ActivityEvent(
                activity_id=act.id,
                event_type="first_seen",
                new_value=data["registration_status"],
            ))
            result.new_count += 1
            continue

        old_status = existing.registration_status
        new_status = data["registration_status"]

        # A weak listing card must not erase a status learned from a detail page.
        if new_status == "unknown" and old_status != "unknown":
            data["registration_status"] = old_status
            new_status = old_status

        changed_fields: list[str] = []
        for key in _MEANINGFUL_FIELDS:
            value = data.get(key)
            old_value = getattr(existing, key)
            if value in (None, "") and old_value not in (None, ""):
                continue
            if key == "is_free" and value is False and data.get("price") is None:
                continue
            if value != old_value:
                changed_fields.append(key)

        status_changed = old_status != new_status
        if status_changed:
            event_type = (
                "reg_opened"
                if new_status == "open" and old_status in ("not_yet_open", "unknown")
                else "status_change"
            )
            db.add(ActivityEvent(
                activity_id=existing.id,
                event_type=event_type,
                old_value=old_status,
                new_value=new_status,
            ))

        if changed_fields and not status_changed:
            db.add(ActivityEvent(
                activity_id=existing.id,
                event_type="details_changed",
                new_value=", ".join(changed_fields)[:200],
            ))

        if status_changed or changed_fields:
            result.changed_count += 1
            existing.enriched_at = None

        for key, value in data.items():
            # Listing cards carry less detail than enriched records: never blank
            # out a known value or shorten a useful description.
            if key == "description" and len(value or "") < len(existing.description or ""):
                continue
            if value in (None, "") and getattr(existing, key) not in (None, ""):
                continue
            if key == "is_free" and value is False and data.get("price") is None:
                continue
            setattr(existing, key, value)
        existing.last_seen_at = now
        existing.last_scraped_at = now
        existing.stale = False

    considered = result.accepted_count + result.rejected_count
    acceptance_ratio = result.accepted_count / considered if considered else 0.0
    coverage_ratio = (
        result.accepted_count / previous_active if previous_active else 1.0
    )
    safe_to_stale = (
        bool(seen_ids)
        and acceptance_ratio >= 0.25
        and (previous_active < 10 or coverage_ratio >= 0.20)
    )

    if safe_to_stale:
        result.stale_marked = (
            db.query(Activity)
            .filter(
                Activity.source_id == source.id,
                Activity.external_id.notin_(seen_ids),
                Activity.stale.is_(False),
            )
            .update({"stale": True}, synchronize_session=False)
        )
    elif previous_active and (raw_items or result.rejected_count):
        result.staling_skipped = True

    db.commit()
    return result


def find_opening_soon(db: Session, hours: int = 48) -> list[Activity]:
    """Find upcoming registration windows that have not been flagged before."""
    # Provider opening times are stored as local wall-clock values.
    now = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    horizon = now + timedelta(hours=hours)
    candidates = (
        db.query(Activity)
        .filter(
            Activity.registration_opens_at.isnot(None),
            Activity.registration_opens_at > now,
            Activity.registration_opens_at <= horizon,
            Activity.stale.is_(False),
            Activity.excluded.is_(False),
        )
        .all()
    )
    out = []
    for act in candidates:
        already = any(e.event_type == "reg_opening_soon" for e in act.events)
        if not already:
            db.add(ActivityEvent(
                activity_id=act.id,
                event_type="reg_opening_soon",
                new_value=str(act.registration_opens_at),
            ))
            out.append(act)
    db.commit()
    return out
