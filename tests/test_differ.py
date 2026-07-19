from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Activity, Source
from app.services.differ import apply_scrape


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_quality_gate_prevents_noise_from_entering_database():
    db = make_db()
    source = Source(
        name="Test Museum",
        slug="test-museum",
        platform="custom",
        homepage_url="https://example.org",
        catalog_url="https://example.org/programs",
        default_category="stem / education",
    )
    db.add(source)
    db.commit()

    result = apply_scrape(db, source, [{
        "name": "View All Programs",
        "description": "Youth camps classes registration learn more",
        "signup_url": "https://example.org/programs",
    }])

    assert result.rejected_count == 1
    assert result.accepted_count == 0
    assert db.query(Activity).count() == 0


def test_valid_activity_is_inserted():
    db = make_db()
    source = Source(
        name="Test Museum",
        slug="test-museum",
        platform="custom",
        homepage_url="https://example.org",
        catalog_url="https://example.org/programs",
        default_category="stem / education",
    )
    db.add(source)
    db.commit()

    result = apply_scrape(db, source, [{
        "name": "Youth Robotics Camp",
        "description": "A week-long coding and robotics program for grades 3-6.",
        "age_text": "Grades 3-6",
        "price_text": "$199",
        "start_date": "2026-08-03",
        "registration_status": "open",
        "signup_url": "https://example.org/programs/robotics-123",
    }])

    assert result.new_count == 1
    assert result.accepted_count == 1
    assert db.query(Activity).one().name == "Youth Robotics Camp"
