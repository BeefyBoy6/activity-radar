"""Seed the database: all 33 sources + starter activities.

Starter activities are curated from the July 2026 research reports so the
dashboard is useful before any scraper runs. They use external_id prefix
"seed-" and get replaced/expired naturally as real scrapes come in.

Run:  python -m seed.seed        (from the project root)
      python -m seed.seed --wipe (drop and recreate everything)
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine, ensure_schema
from app.models import Activity, ActivityEvent, Source, utcnow

TODAY = date.today()


def d(days: int) -> date:
    return TODAY + timedelta(days=days)


def dt(days: int, hour: int = 8) -> datetime:
    base = TODAY + timedelta(days=days)
    return datetime(base.year, base.month, base.day, hour, 0)


# --------------------------------------------------------------------------
# 33 sources, grouped by platform
# --------------------------------------------------------------------------
SOURCES = [
    # --- Rec1 / CivicRec ---
    dict(slug="little-canada", name="Little Canada Parks & Recreation", platform="rec1",
         homepage_url="https://www.littlecanadamn.org/184/Parks-Recreation",
         catalog_url="https://secure.rec1.com/MN/little-canada-mn/catalog",
         default_category="parks & rec / community ed"),
    dict(slug="new-brighton", name="New Brighton Parks & Recreation", platform="rec1",
         homepage_url="https://www.newbrightonmn.gov/297/Parks-Recreation",
         catalog_url="https://secure.rec1.com/MN/new-brighton-mn/catalog",
         default_category="parks & rec / community ed"),
    dict(slug="mounds-view-cc", name="Mounds View Community Center", platform="rec1",
         homepage_url="https://www.moundsviewmn.gov/residents/mounds_view_community_center/index.php",
         catalog_url="https://secure.rec1.com/MN/mounds-view-mn/catalog",
         default_category="ymca / community centers"),
    dict(slug="shoreview-cc", name="Shoreview Community Center", platform="rec1",
         homepage_url="https://www.shoreviewcommunitycenter.com",
         catalog_url="https://secure.rec1.com/MN/shoreview-mn/catalog",
         default_category="ymca / community centers"),

    # --- Dash by DaySmart ---
    dict(slug="roseville-parks", name="Roseville Parks & Recreation", platform="dash",
         homepage_url="https://www.cityofroseville.com/3525/Activities-and-Programs",
         catalog_url="https://apps.daysmartrecreation.com/dash/x/#/online/roseville/programs",
         default_category="parks & rec / community ed"),

    # --- ARUX (ISD 623 migrated off Eleyo — isd623.ce.eleyo.com now just
    #     banners to roseville.arux.app, which is server-rendered) ---
    dict(slug="roseville-commed", name="Roseville Area Schools Community Ed (ISD 623)", platform="arux",
         homepage_url="https://communityed.isd623.org",
         catalog_url="https://roseville.arux.app",
         default_category="parks & rec / community ed"),

    # --- ARUX ---
    dict(slug="moundsview-commed", name="Mounds View Community Ed (ISD 621)", platform="arux",
         homepage_url="https://communityed.mvpschools.org",
         catalog_url="https://moundsview.arux.app",
         default_category="parks & rec / community ed"),

    # --- RevTrak / VS Cloud ---
    dict(slug="arden-hills", name="Arden Hills Parks & Recreation", platform="revtrak",
         homepage_url="https://www.cityofardenhills.org/203/Recreation-Programs",
         catalog_url="https://cityofardenhills.revtrak.net/RW-Parks-Recreation/",
         default_category="parks & rec / community ed"),
    dict(slug="stpaul-parks", name="St. Paul Parks & Recreation", platform="vscloud",
         homepage_url="https://www.stpaul.gov/departments/parks-and-recreation",
         catalog_url="https://mnsaintpaulweb.myvscloud.com/webtrac/web/splash.html",
         default_category="parks & rec / community ed"),
    dict(slug="stpaul-aquatics", name="St. Paul Aquatics", platform="vscloud",
         homepage_url="https://www.stpaul.gov/departments/parks-and-recreation/aquatics/swimming-lessons",
         catalog_url="https://mnsaintpaulweb.myvscloud.com/webtrac/web/search.html?module=AR&keyword=swim",
         default_category="aquatics"),

    # --- YMCA North ---
    dict(slug="ymca-shoreview", name="Shoreview YMCA", platform="ymca",
         homepage_url="https://www.ymcanorth.org/locations/shoreview_ymca",
         default_category="ymca / community centers"),
    dict(slug="ymca-maplewood", name="Maplewood YMCA Community Center", platform="ymca",
         homepage_url="https://www.ymcanorth.org/locations/maplewood_community_center",
         default_category="ymca / community centers"),
    dict(slug="ymca-whitebear", name="White Bear Area YMCA", platform="ymca",
         homepage_url="https://www.ymcanorth.org/locations/white_bear_area_ymca",
         default_category="ymca / community centers"),

    # --- Custom / other platforms ---
    dict(slug="maplewood-sports", name="Maplewood Youth & Adult Sports", platform="custom",
         homepage_url="https://www.maplewoodmn.gov/2025/Youth-Adult-Sports",
         default_category="athletics"),
    dict(slug="ramsey-parks", name="Ramsey County Parks & Recreation", platform="custom",
         homepage_url="https://www.ramseycountymn.gov/residents/parks-recreation",
         default_category="parks & rec / community ed"),
    dict(slug="bgctc", name="Boys & Girls Clubs of the Twin Cities", platform="custom",
         homepage_url="https://www.bgctc.org",
         default_category="ymca / community centers"),
    dict(slug="mn-jcc", name="Minnesota JCC (Capp Center St. Paul)", platform="custom",
         homepage_url="https://minnesotajcc.org",
         default_category="ymca / community centers"),
    dict(slug="ywca-stpaul", name="YWCA St. Paul", platform="custom",
         homepage_url="https://www.ywcastpaul.org/fitness/aquatics",
         default_category="aquatics"),
    dict(slug="bell-museum", name="Bell Museum", platform="custom",
         homepage_url="https://www.bellmuseum.umn.edu",
         catalog_url="https://www.bellmuseum.umn.edu/camps/",
         default_category="stem / education"),
    dict(slug="science-museum", name="Science Museum of Minnesota", platform="custom",
         homepage_url="https://www.smm.org",
         default_category="stem / education"),
    dict(slug="childrens-museum", name="Minnesota Children's Museum", platform="custom",
         homepage_url="https://mcm.org",
         default_category="stem / education"),
    dict(slug="works-museum", name="The Works Museum", platform="custom",
         homepage_url="https://www.theworks.org",
         catalog_url="https://www.theworks.org/camps/",
         default_category="stem / education"),
    dict(slug="ramsey-library", name="Ramsey County Library", platform="custom",
         homepage_url="https://www.rclreads.org",
         default_category="stem / education"),
    dict(slug="maplewood-nature", name="Maplewood Nature Center", platform="custom",
         homepage_url="https://maplewoodmn.gov/960/Nature-Center",
         default_category="stem / education"),
    dict(slug="bakken-museum", name="The Bakken Museum", platform="custom",
         homepage_url="https://thebakken.org",
         default_category="stem / education"),
    dict(slug="childrens-theatre", name="Children's Theatre Company", platform="custom",
         homepage_url="https://childrenstheatre.org",
         catalog_url="https://childrenstheatre.org/education-and-engagement/for-children-and-families/classes-2/",
         default_category="creative arts"),
    dict(slug="park-square", name="Park Square Theatre", platform="custom",
         homepage_url="https://www.parksquaretheatre.org",
         default_category="creative arts"),
    dict(slug="artstart", name="ArtStart", platform="custom",
         homepage_url="https://artstart.org",
         default_category="creative arts"),
    dict(slug="schubert-club", name="Schubert Club", platform="custom",
         homepage_url="https://schubert.org",
         default_category="creative arts"),
    dict(slug="mcad-youth", name="MCAD Continuing Ed — Youth Programs", platform="custom",
         homepage_url="https://www.mcad.edu/academics/continuing-education",
         catalog_url="https://www.mcad.edu/academics/continuing-education/summer-youth-courses-and-camps",
         default_category="creative arts"),
    dict(slug="i9-sports", name="i9 Sports — Northwest Metro", platform="custom",
         homepage_url="https://www.i9sports.com/franchises/northwest-metro-minneapolis/451",
         default_category="sports leagues"),
    dict(slug="adrenaline", name="Adrenaline Sports Center", platform="custom",
         homepage_url="https://adrenalinesc.com",
         catalog_url="https://adrenalinesc.com/leagues/youth-soccer-leagues/",
         default_category="sports leagues"),
    dict(slug="first-tee", name="First Tee Minnesota", platform="custom",
         homepage_url="https://firstteeminnesota.org",
         default_category="sports leagues"),
]

# --------------------------------------------------------------------------
# Starter activities (curated from the July 2026 research reports)
# fields: slug of source, then Activity kwargs
# --------------------------------------------------------------------------
A = []  # (source_slug, dict)

A += [
    ("roseville-parks", dict(
        name="Youth Gymnastics — Fall Session (Ages 6-14)",
        description="Roseville's year-round gymnastics program with recreational levels and a competition team path.",
        category="athletics", age_text="6-14", age_min=6, age_max=14,
        price=89, price_text="$89 (resident) / $99 non-resident", resident_pricing=True,
        start_date=d(63), schedule_text="Tuesdays 5:30-6:30pm",
        registration_status="not_yet_open", registration_opens_at=dt(22),
        location="Roseville Skating Center")),
    ("roseville-parks", dict(
        name="Ninja Warrior Camp",
        description="Obstacle-course camp building strength, agility and confidence.",
        category="athletics", age_text="6-12", age_min=6, age_max=12,
        price=135, price_text="$135/week",
        start_date=d(24), end_date=d(28), schedule_text="Mon-Fri 9am-12pm",
        registration_status="open")),
    ("roseville-parks", dict(
        name="Hoops and Skills Basketball (Ages 4-11)",
        description="Skill-focused youth basketball with experienced coaches.",
        category="athletics", age_text="4-11", age_min=4, age_max=11,
        price=75, price_text="$75",
        start_date=d(70), schedule_text="Saturdays 10-11am",
        registration_status="not_yet_open", registration_opens_at=dt(36))),
    ("roseville-parks", dict(
        name="Roseville Skate School — Basic Skills",
        description="Learn to Skate USA classes at the Roseville Ice Arena, ages 4-18.",
        category="athletics", age_text="4-18", age_min=4, age_max=18,
        price=112, price_text="$112 + $18.50 annual membership",
        start_date=d(68), schedule_text="Sundays 4:15-5:00pm",
        registration_status="not_yet_open", registration_opens_at=dt(39))),

    ("roseville-commed", dict(
        name="Youth Swim Lessons — Level 3",
        description="86° indoor pool at Aŋpétu Téča Education Center; levels for ages 5-14.",
        category="aquatics", age_text="5-14", age_min=5, age_max=14,
        price=70, price_text="$70 / 8 lessons",
        start_date=d(11), schedule_text="Mon/Wed 6:00-6:45pm",
        registration_status="open",
        location="Aŋpétu Téča Education Center")),
    ("roseville-commed", dict(
        name="Fencing Camp (with MN Sword Play)",
        description="Beginner-friendly fencing camp run with MN Sword Play.",
        category="athletics", age_text="8-14", age_min=8, age_max=14,
        price=145, price_text="$145/week",
        start_date=d(10), end_date=d(14), schedule_text="Mon-Fri 1-4pm",
        registration_status="open")),
    ("roseville-commed", dict(
        name="Theater Camp: Broadway Bound",
        description="A week of singing, acting and staging ending in a mini-showcase.",
        category="creative arts", age_text="7-12", age_min=7, age_max=12,
        price=129, price_text="$129/week",
        start_date=d(17), end_date=d(21), schedule_text="Mon-Fri 9am-12pm",
        registration_status="waitlist")),
    ("roseville-commed", dict(
        name="LEGO Robotics Camp",
        description="Build and program LEGO robots in teams; no experience needed.",
        category="stem / education", age_text="7-12", age_min=7, age_max=12,
        price=159, price_text="$159/week",
        start_date=d(31), end_date=d(35), schedule_text="Mon-Fri 9am-12pm",
        registration_status="open")),
    ("roseville-commed", dict(
        name="Gymnastics — Level 4 (Fall)",
        description="Continuation level; current session waitlisted — fall session opens soon.",
        category="athletics", age_text="6-14", age_min=6, age_max=14,
        price=95, price_text="$95",
        start_date=d(66), schedule_text="Thursdays 6-7pm",
        registration_status="not_yet_open", registration_opens_at=dt(26))),

    ("moundsview-commed", dict(
        name="Art Explorers (Ages 6-10)",
        description="Mixed-media art enrichment: drawing, painting, clay.",
        category="creative arts", age_text="6-10", age_min=6, age_max=10,
        price=79, price_text="$79",
        start_date=d(18), schedule_text="Wednesdays 4:30-5:45pm",
        registration_status="open")),
    ("moundsview-commed", dict(
        name="Coding for Kids — Scratch & Beyond",
        description="Intro coding with Scratch moving toward real projects.",
        category="stem / education", age_text="8-12", age_min=8, age_max=12,
        price=99, price_text="$99",
        start_date=d(40), schedule_text="Tuesdays 4:30-5:45pm",
        registration_status="not_yet_open", registration_opens_at=dt(15))),

    ("stpaul-parks", dict(
        name="Fall Youth Soccer League (Ages 8+)",
        description="Rec league at St. Paul rec centers. FREE registration for ages 9+; no residency requirement.",
        category="sports leagues", age_text="8-14", age_min=8, age_max=14,
        price=0, price_text="Free (ages 9+)", is_free=True,
        start_date=d(60), schedule_text="Games Saturdays",
        registration_status="open")),
    ("stpaul-parks", dict(
        name="Flag Football (Ages 7-14)",
        description="Fall flag football league across St. Paul rec centers.",
        category="sports leagues", age_text="7-14", age_min=7, age_max=14,
        price=0, price_text="Free (ages 9+); $10 under 9", is_free=True,
        start_date=d(62), schedule_text="Weeknight practices + Saturday games",
        registration_status="not_yet_open", registration_opens_at=dt(1, hour=9))),

    ("stpaul-aquatics", dict(
        name="Free Swimming Lessons — Session 3 (St. Paul residents)",
        description="FREE for all St. Paul residents under 18. Eight 45-minute lessons at Como, Highland or Great River.",
        category="aquatics", age_text="3-17", age_min=3, age_max=17,
        price=0, price_text="Free (St. Paul residents under 18)", is_free=True, resident_pricing=True,
        start_date=d(14), schedule_text="Various times",
        registration_status="open",
        location="Como Regional Park Pool / Highland / Great River")),

    ("shoreview-cc", dict(
        name="Summer Discovery Camp (Grades K-6)",
        description="Weekly day camp with Tropics waterpark time, gym games and field trips.",
        category="ymca / community centers", age_text="grades K-6", age_min=5, age_max=12,
        price=210, price_text="$210/week (resident discount available)", resident_pricing=True,
        start_date=d(10), schedule_text="Mon-Fri 7:30am-5:30pm",
        registration_status="open")),
    ("shoreview-cc", dict(
        name="Swim Lessons — Youth Level 4",
        description="Group lessons in the Tropics pool, 85° water. Scholarships for Shoreview residents.",
        category="aquatics", age_text="6-14", age_min=6, age_max=14,
        price=84, price_text="$84",
        start_date=d(16), schedule_text="Tue/Thu 5:15-6:00pm",
        registration_status="open")),

    ("little-canada", dict(
        name="Youth Tennis Lessons",
        description="Beginner/intermediate tennis at Little Canada parks; scholarships available.",
        category="athletics", age_text="6-12", age_min=6, age_max=12,
        price=65, price_text="$65",
        start_date=d(12), schedule_text="Mon/Wed mornings",
        registration_status="open")),

    ("new-brighton", dict(
        name="Red Cross Learn-to-Swim Lessons",
        description="American Red Cross curriculum at Highview Middle School pool.",
        category="aquatics", age_text="4-14", age_min=4, age_max=14,
        price=72, price_text="$72",
        start_date=d(15), schedule_text="Saturdays 9-9:45am",
        registration_status="open")),

    ("mounds-view-cc", dict(
        name="Youth Sports Sampler Camp",
        description="Multi-sport week at the Mounds View Community Center gym.",
        category="athletics", age_text="6-11", age_min=6, age_max=11,
        price=45, price_text="$45",
        start_date=d(23), schedule_text="Mon-Thu 10am-12pm",
        registration_status="open")),

    ("arden-hills", dict(
        name="Ninja Warrior League (Fall)",
        description="Obstacle league using Mounds View district facilities.",
        category="athletics", age_text="6-12", age_min=6, age_max=12,
        price=115, price_text="$115",
        start_date=d(70), schedule_text="Thursdays 6-7pm",
        registration_status="not_yet_open", registration_opens_at=dt(22))),

    ("ymca-shoreview", dict(
        name="Day Camp Heritage (free bussing from Roseville)",
        description="Traditional day camp with free bus pickup from Roseville, Arden Hills, Maplewood, White Bear Lake.",
        category="ymca / community centers", age_text="5-13", age_min=5, age_max=13,
        price=265, price_text="$265/week (member) / $305 non-member", resident_pricing=True,
        start_date=d(10), schedule_text="Mon-Fri, weekly sessions all summer",
        registration_status="open")),
    ("ymca-shoreview", dict(
        name="Swim Strokes (Ages 6-12)",
        description="Stroke development for swimmers who've passed Swim Basics.",
        category="aquatics", age_text="6-12", age_min=6, age_max=12,
        price=102, price_text="$102 member / $128 non-member", resident_pricing=True,
        start_date=d(18), schedule_text="Tuesdays 6:15-7:00pm",
        registration_status="open")),
    ("ymca-maplewood", dict(
        name="Fall Youth Basketball League",
        description="Rec basketball with equal play time; practices + Saturday games.",
        category="sports leagues", age_text="5-12", age_min=5, age_max=12,
        price=95, price_text="$95 member / $120 non-member", resident_pricing=True,
        start_date=d(75), schedule_text="Saturdays",
        registration_status="not_yet_open", registration_opens_at=dt(41))),
    ("ymca-whitebear", dict(
        name="YMCA Swim Team Prep",
        description="Bridge program toward the competitive swim team (ages 5-18 program).",
        category="aquatics", age_text="6-12", age_min=6, age_max=12,
        price=140, price_text="$140/session",
        start_date=d(20), schedule_text="Mon/Wed 5:30-6:15pm",
        registration_status="waitlist")),

    ("bell-museum", dict(
        name="Summer Camp: Planetarium Explorers (Grades 3-5)",
        description="Hands-on astronomy week with daily planetarium time on the U of M St. Paul campus — in zip 55113.",
        category="stem / education", age_text="grades 3-5", age_min=8, age_max=11,
        price=295, price_text="$295/week ($220-425 range; member discounts)",
        start_date=d(24), end_date=d(28), schedule_text="Mon-Fri 9am-4pm",
        registration_status="waitlist",
        location="Bell Museum, 2088 Larpenteur Ave W",
        signup_url="https://www.bellmuseum.umn.edu/camps/")),
    ("bell-museum", dict(
        name="Winter Break Camp (Grades K-8)",
        description="Science day camp over winter break; registration typically opens in fall.",
        category="stem / education", age_text="grades K-8", age_min=5, age_max=14,
        price=240, price_text="$240 (est.)",
        start_date=d(170), schedule_text="Winter break, 9am-4pm",
        registration_status="not_yet_open", registration_opens_at=dt(83),
        signup_url="https://www.bellmuseum.umn.edu/winter-camps/")),

    ("science-museum", dict(
        name="Kitty Andersen Youth Science Center Programs",
        description="Informal STEM learning cohorts at the Science Museum of Minnesota.",
        category="stem / education", age_text="10-18", age_min=10, age_max=18,
        price=0, price_text="Free", is_free=True,
        registration_status="open")),

    ("works-museum", dict(
        name="LEGO Engineering Camp (Ages 7-9)",
        description="Build machines and structures with real engineering concepts at The Works.",
        category="stem / education", age_text="7-9", age_min=7, age_max=9,
        price=230, price_text="$230/session ($120-260 range)",
        start_date=d(30), end_date=d(34), schedule_text="Mon-Fri 9am-3:30pm",
        registration_status="open")),
    ("works-museum", dict(
        name="Code Camp for Girls",
        description="Girls-only coding camp — intro programming through games and robots.",
        category="stem / education", age_text="8-12", age_min=8, age_max=12,
        price=260, price_text="$260/session",
        start_date=d(38), end_date=d(42), schedule_text="Mon-Fri 9am-3:30pm",
        registration_status="open")),

    ("bakken-museum", dict(
        name="Inventors Club (Grades 3-9)",
        description="6-week Saturday makerspace program: plan, make and improve your own invention.",
        category="stem / education", age_text="grades 3-9", age_min=8, age_max=15,
        price=180, price_text="$180 / 6 weeks",
        start_date=d(72), schedule_text="Saturdays 10am-12pm",
        registration_status="not_yet_open", registration_opens_at=dt(46))),

    ("ramsey-library", dict(
        name="Maker Kids — Roseville Library",
        description="Free maker activities at the Roseville branch; take-home kits too.",
        category="stem / education", age_text="6-12", age_min=6, age_max=12,
        price=0, price_text="Free", is_free=True,
        schedule_text="Monthly, check branch calendar",
        registration_status="open")),
    ("ramsey-library", dict(
        name="Youth Chess Club",
        description="Drop-in chess for kids at Ramsey County Library branches.",
        category="stem / education", age_text="6-14", age_min=6, age_max=14,
        price=0, price_text="Free", is_free=True,
        schedule_text="Weekly, check branch calendar",
        registration_status="open")),

    ("maplewood-nature", dict(
        name="Family Nature Programs",
        description="Naturalist-led programs, nature play yard and floating boardwalk. Free admission.",
        category="stem / education", age_text="all ages",
        price=0, price_text="Free", is_free=True,
        schedule_text="See monthly calendar",
        registration_status="open")),

    ("childrens-theatre", dict(
        name="Theatre Arts Training — Fall Classes (Ages 8-10)",
        description="Acting, voice and movement classes at the nation's largest children's theatre.",
        category="creative arts", age_text="8-10", age_min=8, age_max=10,
        price=340, price_text="$340/semester",
        start_date=d(65), schedule_text="Saturdays 10-11:30am",
        registration_status="not_yet_open", registration_opens_at=dt(1, hour=10),
        signup_url="https://childrenstheatre.org/education-and-engagement/for-children-and-families/classes-2/")),

    ("park-square", dict(
        name="Youth Acting Class (Park Square Education)",
        description="Year-round youth acting classes from the SteppingStone/Park Square education program.",
        category="creative arts", age_text="8-14", age_min=8, age_max=14,
        price=250, price_text="$250",
        start_date=d(55), schedule_text="Tuesdays 4:30-6pm",
        registration_status="open")),

    ("artstart", dict(
        name="EcoArts Summer Camp",
        description="Art through the lens of environmental stewardship; creative-reuse projects with ArtScraps materials.",
        category="creative arts", age_text="6-12", age_min=6, age_max=12,
        price=175, price_text="$175/week",
        start_date=d(25), end_date=d(29), schedule_text="Mon-Fri 9am-12pm",
        registration_status="open")),

    ("schubert-club", dict(
        name="After-School Music Lessons",
        description="Subsidized music lessons from Minnesota's oldest arts organization.",
        category="creative arts", age_text="7-17", age_min=7, age_max=17,
        price=60, price_text="$60/semester (subsidized)",
        start_date=d(68), schedule_text="Weekly lesson slots",
        registration_status="not_yet_open", registration_opens_at=dt(33))),

    ("mcad-youth", dict(
        name="Youth Painting & Mixed Media (Ages 6-12)",
        description="Studio art classes at MCAD; scholarships available.",
        category="creative arts", age_text="6-12", age_min=6, age_max=12,
        price=185, price_text="$185",
        start_date=d(32), schedule_text="Saturdays 9:30am-12pm",
        registration_status="open",
        signup_url="https://www.mcad.edu/academics/continuing-education/summer-youth-courses-and-camps")),

    ("i9-sports", dict(
        name="Fall Flag Football League",
        description="Age-appropriate league with equal play time guarantee.",
        category="sports leagues", age_text="5-13", age_min=5, age_max=13,
        price=189, price_text="$189/season",
        start_date=d(59), schedule_text="Saturday practice + game",
        registration_status="open")),

    ("adrenaline", dict(
        name="Youth Indoor Soccer League",
        description="Indoor league at Adrenaline Sports Center; hosts i9 programs.",
        category="sports leagues", age_text="6-12", age_min=6, age_max=12,
        price=150, price_text="$150/season",
        start_date=d(64), schedule_text="Weeknights",
        registration_status="unknown",
        signup_url="https://adrenalinesc.com/leagues/youth-soccer-leagues/")),

    ("first-tee", dict(
        name="Fall Golf Classes (Ages 7-9)",
        description="Golf + life-skills curriculum; all skill levels.",
        category="sports leagues", age_text="7-9", age_min=7, age_max=9,
        price=99, price_text="$99",
        start_date=d(60), schedule_text="Sundays 1-2:30pm",
        registration_status="not_yet_open", registration_opens_at=dt(2, hour=12))),

    ("ramsey-parks", dict(
        name="Junior Golf Camp (Ages 4-17)",
        description="County junior golf academies, leagues and girls clinics.",
        category="athletics", age_text="4-17", age_min=4, age_max=17,
        price=99, price_text="$99",
        start_date=d(21), schedule_text="Weekday mornings",
        registration_status="open")),
    ("ramsey-parks", dict(
        name="Tamarack Nature Center Youth Programs",
        description="Outdoor discovery programs at Tamarack Nature Center.",
        category="stem / education", age_text="4-12", age_min=4, age_max=12,
        price=35, price_text="$35",
        start_date=d(19), schedule_text="Various",
        registration_status="open")),

    ("bgctc", dict(
        name="After-School Program (Grades K-12) — FREE membership",
        description="Academic success, arts, sports and daily meals. Membership is free.",
        category="ymca / community centers", age_text="grades K-12", age_min=5, age_max=18,
        price=0, price_text="Free", is_free=True,
        start_date=d(60), schedule_text="Mon-Fri after school",
        registration_status="open")),

    ("mn-jcc", dict(
        name="Youth Basketball Clinics (Grades K-4)",
        description="Skills clinics at the Capp Center; open to all.",
        category="athletics", age_text="grades K-4", age_min=5, age_max=10,
        price=88, price_text="$88",
        start_date=d(66), schedule_text="Sundays 11am-12pm",
        registration_status="not_yet_open", registration_opens_at=dt(24))),

    ("ywca-stpaul", dict(
        name="Piranhas Swim Club — Juniors (Ages 5-10)",
        description="Entry level of the YWCA's competitive swim program.",
        category="aquatics", age_text="5-10", age_min=5, age_max=10,
        price=150, price_text="$150/session",
        start_date=d(25), schedule_text="Mon/Wed 5-5:45pm",
        registration_status="open")),

    ("maplewood-sports", dict(
        name="Fall Youth Soccer",
        description="City rec soccer run with RevSports and district partners.",
        category="athletics", age_text="5-12", age_min=5, age_max=12,
        price=85, price_text="$85",
        start_date=d(61), schedule_text="Tuesdays + Saturday games",
        registration_status="open")),

    ("childrens-museum", dict(
        name="School Break Camp (Ages 5-10)",
        description="Play-based day camp in the museum's exhibit galleries and maker studio.",
        category="stem / education", age_text="5-10", age_min=5, age_max=10,
        price=95, price_text="$95/day",
        start_date=d(96), schedule_text="School release days 9am-4pm",
        registration_status="not_yet_open", registration_opens_at=dt(55))),
]


def main(wipe: bool = False):
    if wipe:
        Base.metadata.drop_all(engine)
    ensure_schema()

    db = SessionLocal()
    try:
        slug_to_source = {}
        for spec in SOURCES:
            src = db.query(Source).filter_by(slug=spec["slug"]).one_or_none()
            if src is None:
                src = Source(**spec)
                db.add(src)
            else:
                for k, v in spec.items():
                    setattr(src, k, v)
            db.flush()
            slug_to_source[spec["slug"]] = src
        db.commit()

        added = 0
        for i, (slug, kwargs) in enumerate(A):
            src = slug_to_source[slug]
            ext_id = f"seed-{slug}-{i}"
            existing = db.query(Activity).filter_by(source_id=src.id, external_id=ext_id).one_or_none()
            if existing:
                for k, v in kwargs.items():  # refresh seed data in place
                    setattr(existing, k, v)
                continue
            act = Activity(source_id=src.id, external_id=ext_id, **kwargs)
            # stagger first_seen so only a few show the "new today" badge
            act.first_seen_at = utcnow() - timedelta(days=(0 if i % 9 == 0 else 3 + i % 5))
            db.add(act)
            db.flush()
            db.add(ActivityEvent(activity_id=act.id, event_type="first_seen",
                                 new_value=kwargs.get("registration_status", "unknown"),
                                 created_at=act.first_seen_at))
            added += 1
        db.commit()
        print(f"Seeded {len(SOURCES)} sources, added {added} activities.")
    finally:
        db.close()


if __name__ == "__main__":
    main(wipe="--wipe" in sys.argv)
