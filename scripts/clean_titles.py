"""Preview or repair existing activity titles that absorbed card descriptions."""
from __future__ import annotations

import argparse

from app.database import SessionLocal
from app.models import Activity
from app.services.normalizer import clean_activity_title


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes")
    parser.add_argument("--source-id", type=int, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Activity).filter(Activity.stale.is_(False))
        if args.source_id is not None:
            query = query.filter(Activity.source_id == args.source_id)

        changed = 0
        for activity in query.order_by(Activity.id):
            cleaned = clean_activity_title(
                activity.name, activity.description or "", 180
            )
            if not cleaned or cleaned == activity.name:
                continue
            changed += 1
            print(f"{activity.id}: {activity.name!r} -> {cleaned!r}")
            if args.apply:
                activity.name = cleaned

        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(f"{'Updated' if args.apply else 'Would update'} {changed} title(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
