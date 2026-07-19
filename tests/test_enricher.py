from app.services.enricher import _audience_exclusion


def test_adult_breadcrumb_is_excluded():
    excluded, _ = _audience_exclusion(
        "Swimnastics",
        "Adult Enrichment / Health & Fitness",
        "A water exercise class.",
    )
    assert excluded


def test_youth_context_is_not_excluded_for_parent_language():
    excluded, _ = _audience_exclusion(
        "Parent & Child Swim Lessons",
        "Youth Enrichment / Aquatics",
        "An adult must accompany each child ages 2-4.",
    )
    assert not excluded
