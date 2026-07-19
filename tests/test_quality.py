from types import SimpleNamespace

from app.services.quality import evaluate


CUSTOM = SimpleNamespace(
    platform="custom",
    catalog_url="https://example.org/programs",
    homepage_url="https://example.org",
)
STRUCTURED = SimpleNamespace(
    platform="arux",
    catalog_url="https://example.org",
    homepage_url="https://example.org",
)


def test_rejects_navigation_and_non_activities():
    nav = {"name": "View All", "description": "Youth programs and camps"}
    rental = {"name": "Birthday Party Rentals", "description": "For kids ages 5-12"}
    screening = {"name": "Early Childhood Screening", "age_text": "Ages 3-5"}
    birthday = {"name": "Pool Birthday Party Packages", "age_text": "Ages 5-12"}
    pass_card = {"name": "Lap/Open Swim 5-Punch Pass", "age_text": "Ages 3+"}
    assert not evaluate(nav, CUSTOM).accepted
    assert not evaluate(rental, CUSTOM).accepted
    assert not evaluate(screening, CUSTOM).accepted
    assert not evaluate(birthday, CUSTOM).accepted
    assert not evaluate(pass_card, CUSTOM).accepted


def test_rejects_adult_only_candidate():
    item = {
        "name": "Adult Pottery Class 18+",
        "description": "Six-week evening session for adults.",
        "start_date": "2026-09-01",
        "signup_url": "https://example.org/programs/adult-pottery",
    }
    assert not evaluate(item, CUSTOM).accepted


def test_accepts_specific_youth_activity():
    item = {
        "name": "Robotics Camp",
        "description": "A five-day coding and robotics camp for youth in grades 3-6.",
        "age_text": "Grades 3-6",
        "age_min": 8,
        "age_max": 12,
        "price": 199,
        "start_date": "2026-08-03",
        "registration_status": "open",
        "signup_url": "https://example.org/programs/robotics-camp-2481",
    }
    assert evaluate(item, CUSTOM).accepted


def test_structured_short_title_can_pass_with_concrete_details():
    item = {
        "name": "Butter Slime",
        "description": "Make colorful slime and learn about polymers in this hands-on session.",
        "price": 15,
        "start_date": "2026-08-14",
        "registration_status": "open",
        "signup_url": "https://example.org/course/11836/summer/butter-slime",
    }
    assert evaluate(item, STRUCTURED).accepted
