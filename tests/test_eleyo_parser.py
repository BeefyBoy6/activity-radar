from bs4 import BeautifulSoup

from app.scrapers.eleyo import EleyoScraper


def test_cards_do_not_absorb_neighboring_course_text():
    html = """
    <main>
      <section class="grid">
        <article class="card">
          <a href="/course/youth/101/summer/robotics-camp">
            <h3>Robotics Camp</h3>
            <p>Grades 3-6</p><p>$199.00</p>
          </a>
        </article>
        <article class="card">
          <a href="/course/102/summer/adventure-art">
            <h3>Adventure Art</h3>
            <p>Ages 7-10</p><p>$149.00</p>
          </a>
        </article>
      </section>
    </main>
    """
    soup = BeautifulSoup(html, "lxml")
    rows = EleyoScraper()._parse_courses(soup, "https://example.org", set())
    assert len(rows) == 2
    assert rows[0]["name"] == "Robotics Camp"
    assert rows[0]["age_text"] == "Grades 3-6"
    assert "Adventure Art" not in rows[0]["description"]
    assert rows[1]["name"] == "Adventure Art"


def test_arux_style_title_does_not_include_category_or_description():
    description = (
        "Journey to the magical world of Harry Potter and other magical lands. "
        "Build and program magical-themed projects."
    )
    html = f"""
    <article class="course-card">
      <a href="/course/11670/summer/robotic-builders" data-description="{description}">
        <div class="course-title">
          Robotic Builders: Hogwarts and Other Kingdoms with Tech Academy
          Science &amp; Technology {description}
        </div>
      </a>
    </article>
    """
    soup = BeautifulSoup(html, "lxml")
    rows = EleyoScraper()._parse_courses(soup, "https://example.org", set())
    assert len(rows) == 1
    assert rows[0]["name"] == (
        "Robotic Builders: Hogwarts and Other Kingdoms with Tech Academy"
    )
    assert rows[0]["description"].startswith("Journey to the magical world")


def test_arux_slug_bounds_title_when_data_description_is_missing():
    description = (
        "Journey to the magical world of Harry Potter and other magical lands. "
        "Build and program magical-themed projects."
    )
    html = f"""
    <article class="course-card">
      <a href="/course/11670/summer-2026/robotic-builders-hogwarts-and-other-kingdoms-with-tech-academy">
        <div class="course-title">
          Robotic Builders: Hogwarts and Other Kingdoms with Tech Academy
          Science &amp; Technology {description}
        </div>
      </a>
    </article>
    """
    soup = BeautifulSoup(html, "lxml")
    rows = EleyoScraper()._parse_courses(soup, "https://example.org", set())
    assert len(rows) == 1
    assert rows[0]["name"] == (
        "Robotic Builders: Hogwarts and Other Kingdoms with Tech Academy"
    )
