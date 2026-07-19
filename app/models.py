"""ORM models."""
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Naive UTC timestamp for SQLite, without deprecated datetime.utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(50), index=True)  # rec1, dash, eleyo, arux, revtrak, vscloud, ymca, custom
    homepage_url: Mapped[str] = mapped_column(String(500), default="")
    catalog_url: Mapped[str] = mapped_column(String(500), default="")
    default_category: Mapped[str] = mapped_column(String(60), default="parks & rec / community ed")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    last_scrape_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    activities: Mapped[list["Activity"]] = relationship(back_populates="source")
    logs: Mapped[list["ScrapeLog"]] = relationship(back_populates="source")


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(300))  # stable id/hash from the provider

    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), index=True)

    age_min: Mapped[float | None] = mapped_column(Float, nullable=True)   # years; 0.75 = 9 months
    age_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_text: Mapped[str] = mapped_column(String(100), default="")

    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_text: Mapped[str] = mapped_column(String(200), default="")
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    resident_pricing: Mapped[bool] = mapped_column(Boolean, default=False)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    schedule_text: Mapped[str] = mapped_column(String(300), default="")  # e.g. "Tue/Thu 4:30-5:30pm"
    location: Mapped[str] = mapped_column(String(300), default="")

    registration_status: Mapped[str] = mapped_column(String(30), default="unknown", index=True)
    # not_yet_open | open | waitlist | closed | unknown
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    signup_url: Mapped[str] = mapped_column(String(600), default="")

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_scraped_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)  # not present in latest scrape
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # detail page fetched
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)  # adult/senior audience — never shown or alerted

    source: Mapped["Source"] = relationship(back_populates="activities")
    events: Mapped[list["ActivityEvent"]] = relationship(
        back_populates="activity", order_by="ActivityEvent.created_at"
    )


class ActivityEvent(Base):
    """Signup history: first appearance, status changes, registration opening."""
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))  # first_seen | status_change | reg_opened | reg_opening_soon
    old_value: Mapped[str] = mapped_column(String(200), default="")
    new_value: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)

    activity: Mapped["Activity"] = relationship(back_populates="events")


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | error
    activities_found: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    rejection_summary: Mapped[str] = mapped_column(Text, default="")
    staling_skipped: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped["Source"] = relationship(back_populates="logs")


class Setting(Base):
    """Key/value settings, JSON-encoded values."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
