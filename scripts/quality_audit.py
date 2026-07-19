"""Audit existing activity rows with the same quality gate used by scrapes.

Dry run (recommended first):
    python -m scripts.quality_audit --csv data/quality-audit.csv

Hide rejected rows after reviewing the CSV:
    python -m scripts.quality_audit --apply --csv data/quality-audit.csv

Rows are marked stale, not deleted, so history remains intact and a later valid
scrape can restore them.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.database import SessionLocal, ensure_schema
from app.models import Activity
from app.services.quality import evaluate


def activity_data(activity: Activity) -> dict:
    return {column.name: getattr(activity, column.name) for column in Activity.__table__.columns}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="mark rejected active rows stale")
    parser.add_argument("--source", help="audit only one source slug")
    parser.add_argument("--csv", default="data/quality-audit.csv", help="report path")
    args = parser.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        query = db.query(Activity).filter(
            Activity.stale.is_(False),
            Activity.excluded.is_(False),
        )
        if args.source:
            query = query.join(Activity.source).filter_by(slug=args.source)

        activities = query.all()
        audited_count = len(activities)
        rejected = []
        for activity in activities:
            decision = evaluate(activity_data(activity), activity.source)
            if decision.accepted:
                continue
            rejected.append({
                "activity_id": activity.id,
                "source": activity.source.slug,
                "name": activity.name,
                "score": decision.score,
                "reasons": decision.reason_text,
                "signup_url": activity.signup_url,
            })
            if args.apply:
                activity.stale = True

        report_path = Path(args.csv)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("activity_id", "source", "name", "score", "reasons", "signup_url"),
            )
            writer.writeheader()
            writer.writerows(rejected)

        if args.apply:
            db.commit()
        print(
            f"Audited {audited_count} active activities; "
            f"{len(rejected)} rejected. "
            f"{'Marked stale.' if args.apply else 'Dry run only.'} "
            f"Report: {report_path}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
