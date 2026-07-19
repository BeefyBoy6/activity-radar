"""Settings stored in the DB, with validation and environment defaults."""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from ..config import DEFAULT_RADIUS_MIN, DEFAULT_ZIP
from ..models import Setting

log = logging.getLogger("settings")

DEFAULTS: dict = {
    "zip": DEFAULT_ZIP,
    "radius_minutes": DEFAULT_RADIUS_MIN,
    "muted_categories": [],
    "muted_sources": [],
    "notify_new": True,
    "notify_reg_opened": True,
    "notify_opening_soon": True,
    "daily_digest": True,
}


def _decode(row: Setting):
    try:
        return json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        log.warning("ignoring corrupt setting %s", row.key)
        return DEFAULTS.get(row.key)


def _validate(key: str, value):
    if key == "zip":
        text = str(value or "").strip()
        return text[:10] or DEFAULT_ZIP
    if key == "radius_minutes":
        try:
            return max(1, min(180, int(value)))
        except (TypeError, ValueError):
            return DEFAULT_RADIUS_MIN
    if key in {"notify_new", "notify_reg_opened", "notify_opening_soon", "daily_digest"}:
        return bool(value)
    if key == "muted_categories":
        return sorted({str(item).strip().lower() for item in (value or []) if str(item).strip()})
    if key == "muted_sources":
        output = set()
        for item in value or []:
            try:
                output.add(int(item))
            except (TypeError, ValueError):
                continue
        return sorted(output)
    return value


def get_all(db: Session) -> dict:
    stored = {row.key: _decode(row) for row in db.query(Setting).all() if row.key in DEFAULTS}
    return {**DEFAULTS, **stored}


def get(db: Session, key: str):
    row = db.get(Setting, key)
    return DEFAULTS.get(key) if row is None else _decode(row)


def set_many(db: Session, values: dict) -> dict:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        row = db.get(Setting, key)
        if row is None:
            row = Setting(key=key)
            db.add(row)
        row.value = json.dumps(_validate(key, value))
    db.commit()
    return get_all(db)
