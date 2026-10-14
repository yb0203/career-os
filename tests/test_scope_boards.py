"""Mapping helpers for the scope-driven boards. Fake payloads only: no network."""
import json
from datetime import datetime, timedelta, timezone

from pipeline.sources import SOURCES, scope_boards as sb

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def test_all_registered():
    for name in ("unstop", "internshala", "wellfound", "weekday", "remoterocketship", "hasjob"):
        assert name in SOURCES


# ---- Unstop
UNSTOP = {
    "id": 1, "title": "Founder's Office Associate", "subtype": "jobs", "status": "LIVE",
    "seo_url": "https://unstop.com/jobs/founders-office-associate-acme-1",
    "approved_date": "2026-10-10 19:55:49 GMT+0530", "organisation": {"name": "Acme"},
    "details": "<p>Work with the <b>CEO</b>.</p>",
    "locations": [{"city": "Bangalore", "country": "India"}],
    "jobDetail": {"type": "in_office", "timing": "full_time", "paid_unpaid": "paid",
                  "min_salary": 25000, "max_salary": 30000, "pay_in": "monthly", "show_salary": 1},
    "filters": [{"type": "eligible", "name": "Fresher"}],
}


def test_unstop_mapping():
    j = sb._unstop_job(UNSTOP)
    assert (j.company, j.title, j.source) == ("Acme", "Founder's Office Associate", "unstop")
    assert j.location == "Bangalore" and j.remote is None  # no blanket "India": cities must still gate
    assert j.employment_type == "full-time"
    assert j.posted_at == datetime(2026, 10, 10, 14, 25, 49, tzinfo=timezone.utc)
    assert "CEO" in j.description and "<" not in j.description
    assert "Fresher" in j.description and "25000" in j.description


def test_unstop_wfh_internship_and_unpaid():
    j = sb._unstop_job({**UNSTOP, "subtype": "internships", "jobDetail": {"type": "wfh", "paid_unpaid": "unpaid"}})
    assert j.employment_type == "internship" and j.remote is True and j.location == "Remote, India"
    assert sb._unstop_unpaid({"jobDetail": {"paid_unpaid": "unpaid"}})
    assert not sb._unstop_unpaid(UNSTOP)


def test_unstop_fetch_skips_unpaid_and_dedupes(monkeypatch):
    unpaid = {**UNSTOP, "id": 2, "jobDetail": {"type": "wfh", "paid_unpaid": "unpaid"}}
    payload = {"data": {"data": [UNSTOP, UNSTOP, unpaid]}}

    class S:
        def get(self, url, params=None, timeout=None):
            return type("R", (), {"status_code": 200, "json": lambda self: payload})()

    monkeypatch.setattr(sb, "session", lambda: S())
    monkeypatch.setattr(sb, "_sleep", lambda *a: None)
    jobs = sb.unstop({"opportunities": ["jobs"], "terms": ["growth", "strategy"]}, [])
    assert [j.title for j in jobs] == ["Founder's Office Associate"]


# ---- Internshala
CARD = """
<div class="container-fluid individual_internship logged_out_jd_summary " id="individual_internship_1" internshipId="1" employment_type="internship" data-href='/internship/detail/product-management-internship-in-bangalore-at-acme1'>
<h2 class="job-internship-name"><a class="job-title-href" id="job_title" href="/x" target="_blank">Product Management</a></h2>
<p class="company-name">
   Acme Labs   </p>
<div class="row-1-item locations"><i class="ic-16-map-pin"></i><span><a>Bangalore</a></span></div><!-- /location -->
<span class='stipend'>&#8377; 30,000 - 40,000 /month</span>
<div class="about_job"><div class="text">About the internship We want a PM.</div></div>
<div class="status-success"><i class="ic-16-reschedule"></i><span>3 days ago</span></div>
<span>Fresher Job</span>
</div>
<div class="container-fluid individual_internship" id="individual_internship_2" internshipId="2" employment_type="internship" data-href='/internship/detail/unpaid-one'>
<a class="job-title-href" href="/y">Growth</a><p class="company-name">NoPay Co</p>
<div class="row-1-item locations"><span><a>Work from home</a></span></div><!-- /location -->
<span class='stipend'>Unpaid</span>
</div>
"""


def test_internshala_cards_and_unpaid_filter():
    jobs = sb._internshala_cards(CARD, now=NOW)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.company, j.title, j.location) == ("Acme Labs", "Product Management", "Bangalore")
    assert j.url == "https://internshala.com/internship/detail/product-management-internship-in-bangalore-at-acme1"
    assert j.employment_type == "internship" and j.posted_at == NOW - timedelta(days=3)
    assert "30,000" in j.description and "Fresher friendly" in j.description
    assert len(sb._internshala_cards(CARD, now=NOW, include_unpaid=True)) == 2


def test_ago_parsing():
    assert sb._ago("Just now", NOW) == NOW
    assert sb._ago("2 weeks ago", NOW) == NOW - timedelta(days=14)
    assert sb._ago("1 month ago", NOW) == NOW - timedelta(days=30)
    assert sb._ago("5 hours ago", NOW) == NOW - timedelta(hours=5)
    assert sb._ago("garbage", NOW) is None


# ---- Wellfound
APOLLO = {
    "StartupResult:9": {"name": "Zixflow", "highlightedJobListings": [{"__ref": "JobListingSearchResult:1"},
                                                                       {"__ref": "JobListingSearchResult:2"}]},
    "JobListingSearchResult:1": {
        "id": "1", "slug": "product-manager", "title": "Product Manager", "locationNames": ["Bengaluru"],
        "remote": False, "remoteConfig": {"kind": "ONSITE"}, "compensation": "3L - 12L", "yearsExperienceMin": 3,
        "liveStartAt": 1790749040, "jobType": "full-time", "description": "Own the **roadmap** &amp; ship."},
    "JobListingSearchResult:2": {
        "id": "2", "slug": "chief-of-staff", "title": "Chief of Staff", "locationNames": [],
        "acceptedRemoteLocationNames": ["India"], "remoteConfig": {"kind": "REMOTE"}, "description": ""},
    "JobListingSearchResult:3": {"id": "3", "title": "Orphan", "locationNames": ["Pune"]},  # no company
}


def test_wellfound_mapping():
    jobs = {j.title: j for j in sb._wellfound_jobs(APOLLO)}
    assert set(jobs) == {"Product Manager", "Chief of Staff"}
    pm = jobs["Product Manager"]
    assert (pm.company, pm.location, pm.source) == ("Zixflow", "Bengaluru", "wellfound")
    assert pm.url == "https://wellfound.com/jobs/1-product-manager"
    assert "3+ years experience" in pm.description and "3L - 12L" in pm.description and "&amp;" not in pm.description
    assert pm.posted_at is not None and pm.posted_at.year == 2026
    cos = jobs["Chief of Staff"]
    assert cos.remote is True and cos.location == "Remote, India"


# ---- Weekday
SITEMAP = """<urlset>
<url><loc>https://jobs.weekday.works/product-manager-at-acme-wkdy1</loc><lastmod>2026-10-08T09:00:00.000Z</lastmod></url>
<url><loc>https://jobs.weekday.works/senior-java-developer-at-acme-wkdy2</loc><lastmod>2026-10-08T09:30:00.000Z</lastmod></url>
<url><loc>https://jobs.weekday.works/founders-office-at-beta-wkdy3</loc><lastmod>2026-10-09T09:00:00.000Z</lastmod></url>
<url><loc>https://jobs.weekday.works/growth-manager-at-old-wkdy4</loc><lastmod>2026-08-01T09:00:00.000Z</lastmod></url>
</urlset>"""


def test_weekday_candidates_filter_and_order():
    c = sb._weekday_candidates(SITEMAP, datetime(2026, 10, 14, tzinfo=timezone.utc), 14)
    assert [u.rsplit("/", 1)[1] for u, _ in c] == ["founders-office-at-beta-wkdy3", "product-manager-at-acme-wkdy1"]


LD = {"@type": "JobPosting", "title": "Product Manager", "datePosted": "2026-10-08T07:55:02.000Z",
      "description": "<p>Own <b>AI</b> products. 3+ years of experience.</p>", "employmentType": "FULL_TIME",
      "hiringOrganization": {"name": "Korza"},
      "jobLocation": [{"address": {"addressRegion": "Mumbai, Maharashtra, India"}}]}


def test_weekday_job_mapping_keeps_city_drops_country():
    j = sb._weekday_job(LD, "https://jobs.weekday.works/x")
    assert (j.company, j.title, j.source, j.employment_type) == ("Korza", "Product Manager", "weekday", "full-time")
    assert j.location == "Mumbai, Maharashtra"
    assert "<" not in j.description
    only_country = {**LD, "jobLocation": [{"address": {"addressRegion": "India"}}]}
    assert sb._weekday_job(only_country, "u").location == "India"


def test_job_posting_extraction():
    page = ('<script type="application/ld+json">{"@type": "BreadcrumbList"}</script>'
            f'<script type="application/ld+json">{json.dumps(LD)}</script>')
    assert sb._job_posting(page)["title"] == "Product Manager"
    assert sb._job_posting("<html></html>") is None


# ---- Remote Rocketship
ROCKET = {"id": 7, "roleTitle": "Product Manager - Fintech", "url": "https://boards.greenhouse.io/x/jobs/1",
          "location": "India", "locationType": "remote", "created_at": "2026-10-12T10:00:00.000+00:00",
          "employmentType": "full-time", "isMidLevel": True, "company": {"name": "Shuru"},
          "jobDescriptionSummary": "Lead payments product."}


def test_rocketship_mapping():
    j = sb._rocketship_job(ROCKET)
    assert (j.company, j.title, j.location, j.remote) == ("Shuru", "Product Manager - Fintech", "India", True)
    assert j.url.startswith("https://boards.greenhouse.io") and j.apply_via == "greenhouse"
    assert "mid level" in j.description and "payments" in j.description
    assert j.posted_at is not None and j.posted_at.day == 12


# ---- Hasjob
FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>All jobs</title>
<entry><title type="text">Product Manager</title><link href="https://hasjob.co/acme/abc"/>
<published>2026-10-12T08:55:45.258001+00:00</published><location>Anywhere</location>
<content type="html">&lt;p&gt;&lt;strong&gt;Acme Co&lt;/strong&gt;&lt;br/&gt;Anywhere&lt;/p&gt;&lt;p&gt;Build things.&lt;/p&gt;</content></entry>
</feed>"""


def test_hasjob_mapping():
    (j,) = sb._hasjob_entries(FEED)
    assert (j.company, j.title, j.location, j.remote) == ("Acme Co", "Product Manager", "Anywhere", True)
    assert j.url == "https://hasjob.co/acme/abc" and "Build things" in j.description
