"""Settings stored in the DB (mutable from the admin UI), with env defaults."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..config import DEFAULT_RADIUS_MIN, DEFAULT_ZIP
from ..models import Setting

DEFAULTS: dict = {
    "zip": DEFAULT_ZIP,
    "radius_minutes": DEFAULT_RADIUS_MIN,
    "muted_categories": [],   # list[str]
    "muted_sources": [],      # list[int] source ids
    "notify_new": True,
    "notify_reg_opened": True,
    "notify_opening_soon": True,
    "daily_digest": True,
}


def get_all(db: Session) -> dict:
    stored = {s.key: json.loads(s.value) for s in db.query(Setting).all()}
    return {**DEFAULTS, **stored}


def get(db: Session, key: str):
    row = db.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key)
    return json.loads(row.value)


def set_many(db: Session, values: dict) -> dict:
    for key, val in values.items():
        if key not in DEFAULTS:
            continue
        row = db.get(Setting, key)
        if row is None:
            row = Setting(key=key)
            db.add(row)
        row.value = json.dumps(val)
    db.commit()
    return get_all(db)
