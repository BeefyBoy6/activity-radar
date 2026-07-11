"""REST API for the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..config import CATEGORIES
from ..models import Activity, ActivityEvent, ScrapeLog, Source
from ..services import runner, settings_store

router = APIRouter(prefix="/api")


def _activity_dict(a: Activity, new_cutoff: datetime) -> dict:
    # every card gets a working link: the activity's own registration page,
    # else the org's catalog, else its homepage
    signup = a.signup_url or (a.source and (a.source.catalog_url or a.source.homepage_url)) or ""
    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "category": a.category,
        "organization": a.source.name if a.source else "",
        "source_id": a.source_id,
        "age_text": a.age_text,
        "age_min": a.age_min,
        "age_max": a.age_max,
        "price": a.price,
        "price_text": a.price_text,
        "is_free": a.is_free,
        "resident_pricing": a.resident_pricing,
        "start_date": a.start_date.isoformat() if a.start_date else None,
        "end_date": a.end_date.isoformat() if a.end_date else None,
        "schedule_text": a.schedule_text,
        "location": a.location,
        "registration_status": a.registration_status,
        "registration_opens_at": a.registration_opens_at.isoformat() if a.registration_opens_at else None,
        "signup_url": signup,
        "first_seen_at": a.first_seen_at.isoformat(),
        "last_scraped_at": a.last_scraped_at.isoformat(),
        "is_new": a.first_seen_at >= new_cutoff,
        "stale": a.stale,
    }


@router.get("/activities")
def list_activities(
    db: Session = Depends(get_db),
    category: str | None = None,
    status: str | None = None,
    organization: int | None = Query(None, description="source id"),
    free_only: bool = False,
    age: float | None = Query(None, description="child age in years; filters eligibility"),
    q: str | None = None,
    include_stale: bool = False,
    sort: str = Query("reg_opens", pattern="^(reg_opens|start_date|price|name|newest)$"),
    limit: int = Query(500, le=2000),
):
    query = (db.query(Activity).options(joinedload(Activity.source))
             .filter(Activity.excluded.is_(False)))
    if not include_stale:
        query = query.filter(Activity.stale.is_(False))
    if category:
        query = query.filter(Activity.category == category.lower())
    if status:
        query = query.filter(Activity.registration_status == status)
    if organization:
        query = query.filter(Activity.source_id == organization)
    if free_only:
        query = query.filter(Activity.is_free.is_(True))
    if age is not None:
        query = query.filter(
            or_(Activity.age_min.is_(None), Activity.age_min <= age),
            or_(Activity.age_max.is_(None), Activity.age_max >= age),
        )
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Activity.name.ilike(like), Activity.description.ilike(like)))

    if sort == "reg_opens":
        query = query.order_by(Activity.registration_opens_at.is_(None),
                               Activity.registration_opens_at)
    elif sort == "start_date":
        query = query.order_by(Activity.start_date.is_(None), Activity.start_date)
    elif sort == "price":
        query = query.order_by(Activity.price.is_(None), Activity.price)
    elif sort == "newest":
        query = query.order_by(Activity.first_seen_at.desc())
    else:
        query = query.order_by(func.lower(Activity.name))

    new_cutoff = datetime.utcnow() - timedelta(hours=24)
    return [_activity_dict(a, new_cutoff) for a in query.limit(limit).all()]


@router.get("/activities/{activity_id}")
def get_activity(activity_id: int, db: Session = Depends(get_db)):
    a = db.get(Activity, activity_id)
    if not a:
        raise HTTPException(404)
    d = _activity_dict(a, datetime.utcnow() - timedelta(hours=24))
    d["events"] = [
        {"type": e.event_type, "old": e.old_value, "new": e.new_value,
         "at": e.created_at.isoformat()}
        for e in a.events
    ]
    return d


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    """Categories, orgs, and counts for filter UI + header stats."""
    new_cutoff = datetime.utcnow() - timedelta(hours=24)
    active = db.query(Activity).filter(Activity.stale.is_(False),
                                       Activity.excluded.is_(False))
    return {
        "categories": CATEGORIES,
        "organizations": [
            {"id": s.id, "name": s.name, "active": s.active}
            for s in db.query(Source).order_by(Source.name).all()
        ],
        "stats": {
            "total": active.count(),
            "open": active.filter(Activity.registration_status == "open").count(),
            "not_yet_open": active.filter(Activity.registration_status == "not_yet_open").count(),
            "new_today": active.filter(Activity.first_seen_at >= new_cutoff).count(),
        },
    }


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    out = []
    for s in db.query(Source).order_by(Source.name).all():
        last_log = (db.query(ScrapeLog).filter_by(source_id=s.id)
                    .order_by(ScrapeLog.started_at.desc()).first())
        out.append({
            "id": s.id, "name": s.name, "slug": s.slug, "platform": s.platform,
            "homepage_url": s.homepage_url, "catalog_url": s.catalog_url,
            "default_category": s.default_category, "active": s.active,
            "last_scrape_at": s.last_scrape_at.isoformat() if s.last_scrape_at else None,
            "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
            "error_count": s.error_count,
            "activity_count": db.query(Activity).filter_by(source_id=s.id)
                                .filter(Activity.stale.is_(False),
                                        Activity.excluded.is_(False)).count(),
            "last_status": last_log.status if last_log else None,
            "last_error": (last_log.error.splitlines()[0] if last_log and last_log.error else ""),
        })
    return out


@router.patch("/sources/{source_id}")
def update_source(source_id: int, payload: dict, db: Session = Depends(get_db)):
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404)
    for key in ("active", "catalog_url", "default_category", "notes"):
        if key in payload:
            setattr(s, key, payload[key])
    db.commit()
    return {"ok": True}


@router.post("/scrape")
def scrape_now(background: BackgroundTasks, source_id: int | None = None):
    background.add_task(runner.run_all, source_id)
    return {"started": True, "source_id": source_id}


@router.get("/logs")
def logs(db: Session = Depends(get_db), limit: int = 100):
    rows = (db.query(ScrapeLog).options(joinedload(ScrapeLog.source))
            .order_by(ScrapeLog.started_at.desc()).limit(limit).all())
    return [{
        "id": r.id,
        "source": r.source.name if r.source else r.source_id,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "status": r.status,
        "found": r.activities_found,
        "new": r.new_count,
        "changed": r.changed_count,
        "error": r.error,
    } for r in rows]


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return settings_store.get_all(db)


@router.put("/settings")
def put_settings(payload: dict, db: Session = Depends(get_db)):
    return settings_store.set_many(db, payload)
