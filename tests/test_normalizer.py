from datetime import date

from app.services.normalizer import (
    clean_activity_title,
    extract_age_text,
    parse_age_range,
    parse_date,
    parse_status,
    safe_http_url,
    normalize,
)


def test_age_extraction_stops_before_description():
    assert extract_age_text("Level 1, Ages 9+ Students will learn to float") == "Ages 9+"
    assert extract_age_text("Grades K - 2, Monday through Friday") == "Grades K - 2"
    assert extract_age_text("Toddlers 9-24 months") == "9-24 months"


def test_grade_and_month_age_parsing():
    assert parse_age_range("Grades 2-6") == (7.0, 12.0)
    assert parse_age_range("9 months - 3 years") == (0.75, 3.0)


def test_registration_open_date_is_not_misclassified_as_open():
    assert parse_status("Registration opens August 1") == "not_yet_open"
    assert parse_status("Registration is open — register now") == "open"
    assert parse_status("Join the waitlist") == "waitlist"
    assert parse_status("A full-day camp with closed-toe shoes required") == "unknown"


def test_url_scheme_filter():
    assert safe_http_url("https://example.org/program/1") == "https://example.org/program/1"
    assert safe_http_url("javascript:alert(1)") == ""
    assert safe_http_url("#details") == ""


def test_iso_date():
    assert parse_date("2026-08-17") == date(2026, 8, 17)


def test_normalize_drops_garbage_age_capture():
    item = normalize({"name": "Art Camp", "age_text": "care program"}, "creative arts")
    assert item["age_text"] == ""



def test_clean_activity_title_removes_arux_description_and_category():
    description = (
        "Journey to the magical world of Harry Potter and other magical lands. "
        "Build and program magical-themed projects."
    )
    raw = (
        "Robotic Builders: Hogwarts and Other Kingdoms with Tech Academy "
        "Science & Technology " + description + " Young imaginations soar!"
    )
    assert clean_activity_title(raw, description) == (
        "Robotic Builders: Hogwarts and Other Kingdoms with Tech Academy"
    )


def test_clean_activity_title_removes_status_category_and_lunch_description():
    description = (
        "Students registered for both morning and afternoon camps at Emmet D. "
        "Williams Elementary are invited to stay in-between to eat lunch."
    )
    raw = (
        "Starting Soon Let's Do Lunch @ Emmet D. Williams Elementary "
        "Special Interest " + description
    )
    assert clean_activity_title(raw, description) == (
        "Let's Do Lunch @ Emmet D. Williams Elementary"
    )


def test_clean_activity_title_preserves_legitimate_category_words():
    assert clean_activity_title(
        "Girls in Science & Technology",
        "A hands-on program for curious students.",
    ) == "Girls in Science & Technology"
