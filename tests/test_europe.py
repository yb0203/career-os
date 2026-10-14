"""Europe search: classification, source parsing and sheet merge. No network."""
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import europe, europe_ats, europe_sheet
from pipeline.europe import (apply_method, classify, find_countries, load_config, merge_duplicates,
                             parse_relocate, required_years, sponsorship_signal)
from pipeline.models import Job

CFG = load_config()


def job(title="AI Engineer", location="Stockholm, Sweden", description="", **kw):
    kw.setdefault("company", "Acme")
    kw.setdefault("url", "https://boards.greenhouse.io/acme/jobs/1")
    kw.setdefault("source", "greenhouse")
    return Job(title=title, location=location, description=description, **kw)


# ---- config
def test_config_compiles_and_watchlist_uses_known_ats():
    assert {n for n, nordic, *_ in CFG["_countries"] if nordic} == {"Sweden", "Norway", "Denmark", "Finland", "Iceland"}
    assert CFG["watchlist"], "watchlist must not be empty"
    for company, spec in CFG["watchlist"].items():
        assert spec and set(spec) <= set(europe_ats.ATS_FETCHERS), company


# ---- countries
def test_find_countries_from_cities_and_codes():
    assert [c for c, _ in find_countries("Stockholm", CFG)] == ["Sweden"]
    got = find_countries("Copenhagen / London / Berlin", CFG)
    assert [c for c, _ in got] == ["Denmark", "United Kingdom", "Germany"]
    assert dict(got)["Denmark"] is True and dict(got)["Germany"] is False
    assert [c for c, _ in find_countries("Berlin, BE, DE", CFG, "smartrecruiters")] == ["Germany"]  # not Belgium
    assert find_countries("San Francisco, CA", CFG) == []
    assert find_countries("Oslo, Norway", CFG)[0] == ("Norway", True)


# ---- sponsorship text
@pytest.mark.parametrize("text,kind", [
    ("We offer visa sponsorship for this role.", "sponsor"),
    ("Relocation support is available for the right candidate.", "relocation"),
    ("We will help you relocate to Berlin.", "relocation"),
    ("We can sponsor a work permit or EU Blue Card.", "sponsor"),
])
def test_positive_phrases(text, kind):
    assert sponsorship_signal(text, CFG)[:1] == (kind,)


@pytest.mark.parametrize("text", [
    "Unfortunately we are unable to offer visa sponsorship.",
    "No sponsorship available.",
    "We do not sponsor work permits.",
    "EU citizens only.",
    "No relocation assistance is offered.",
])
def test_strong_negatives_reject(text):
    kind, _ev, verdict = sponsorship_signal("Great role. " + text, CFG)
    assert kind is None and verdict == "rejected_strong"


def test_right_to_work_alone_is_a_soft_reject_but_explicit_offer_wins():
    assert sponsorship_signal("You must have the right to work in the UK.", CFG)[2] == "rejected_soft"
    kind, _ev, verdict = sponsorship_signal("You need the right to work in the UK. We also offer visa sponsorship.", CFG)
    assert kind == "sponsor" and verdict == "ok-soft"


def test_years_of_experience():
    assert required_years("3+ years of experience with Python") == 3
    assert required_years("7+ years experience building platforms") == 7
    assert required_years("We value diversity. Founded 20 years ago.") == 0


# ---- classification
def test_sponsored_junior_ai_role_in_nordics_scores_high():
    row = classify(job("Junior AI Engineer", description="We offer visa sponsorship and relocation support. 1-2 years of experience."), CFG)
    assert row and row["Family"] == "Engineering" and row["AI"] == "Yes"
    assert row["Country"] == "Sweden" and row["Nordic"] == "Yes" and row["Visa/Relocation"] == "sponsor"
    assert row["Apply method"] == "Direct (no login)" and row["Score"] >= 90
    assert row["ID"] == job("Junior AI Engineer").id


def test_no_signal_means_not_listed():
    assert classify(job("AI Engineer", description="Great team, great perks."), CFG) is None


def test_negative_sponsorship_rejected_even_when_remote():
    assert classify(job("AI Engineer", "Remote - EMEA", description="We cannot sponsor visas."), CFG) is None


@pytest.mark.parametrize("title", [
    "Senior AI Engineer", "Staff Software Engineer", "Principal Product Manager", "Head of Product",
    "Engineering Manager", "Sales Engineer", "Account Executive", "Marketing Manager", "Product Designer",
    "Software Engineering Intern", "iOS Engineer", "Solutions Engineer",
])
def test_wrong_level_or_function_dropped(title):
    assert classify(job(title, description="We offer visa sponsorship."), CFG) is None


def test_ai_solutions_engineer_is_kept():
    assert classify(job("AI Solutions Engineer", description="Visa sponsorship available."), CFG)


def test_product_family():
    row = classify(job("Associate Product Manager", "Berlin, Germany", description="Relocation support provided."), CFG)
    assert row["Family"] == "Product" and row["Country"] == "Germany" and row["Visa/Relocation"] == "relocation"
    assert classify(job("Technical Program Manager", "Dublin, Ireland", description="Visa sponsorship offered."), CFG)


def test_too_many_years_dropped():
    assert classify(job("Backend Engineer", description="8+ years of experience. We offer visa sponsorship."), CFG) is None
    assert classify(job("Backend Engineer", description="3+ years of experience. We offer visa sponsorship."), CFG)


def test_non_european_sponsor_role_dropped():
    assert classify(job("Backend Engineer", "San Francisco, CA", description="We offer visa sponsorship."), CFG) is None


def test_remote_worldwide_and_eu_remote_and_single_country_remote():
    ww = classify(job("Backend Engineer", "Remote - Worldwide", remote=True, source="remotive",
                      url="https://remotive.com/x"), CFG)
    assert ww["Visa/Relocation"] == "remote-worldwide" and ww["Country"] == "Worldwide (remote)"
    assert ww["Apply method"] == "Aggregator"
    eu = classify(job("Product Manager", "Remote - EMEA", remote=True), CFG)
    assert eu["Visa/Relocation"] == "remote-check" and eu["Country"] == "Europe (remote)"
    assert classify(job("Backend Engineer", "Remote, Germany", remote=True), CFG) is None
    assert classify(job("Backend Engineer", "Remote - US", remote=True), CFG) is None


def test_remote_blurb_does_not_make_a_country_pinned_role_worldwide():
    row = classify(job("Backend Engineer", "Vilnius / Kaunas", remote=True,
                       description="Work from anywhere in the world!"), CFG)
    assert row is None


def test_hint_from_source_counts_but_strong_negative_still_wins():
    j = job("Backend Engineer", "Berlin", source="arbeitnow", url="https://www.arbeitnow.com/jobs/x")
    row = classify(j, CFG, hint="sponsor")
    assert row["Visa/Relocation"] == "sponsor" and row["Apply method"] == "Aggregator"
    j2 = job("Backend Engineer", "Berlin", description="No visa sponsorship.", source="arbeitnow")
    assert classify(j2, CFG, hint="sponsor") is None


def test_stale_posting_dropped():
    old = datetime.now(timezone.utc) - timedelta(days=400)
    assert classify(job("AI Engineer", description="Visa sponsorship.", posted_at=old), CFG) is None


def test_direct_apply_outranks_aggregator():
    d = classify(job("AI Engineer", description="Visa sponsorship."), CFG)
    a = classify(job("AI Engineer", description="Visa sponsorship.", url="https://relocate.me/x", source="relocate.me"), CFG)
    assert d["Score"] > a["Score"]


@pytest.mark.parametrize("url,expected", [
    ("https://jobs.lever.co/x/1", "Direct (no login)"), ("https://jobs.ashbyhq.com/x/1", "Direct (no login)"),
    ("https://acme.jobs.personio.de/job/1", "Direct (no login)"), ("https://acme.wd3.myworkdayjobs.com/en/1", "Account needed"),
    ("https://www.arbeitnow.nl/jobs/x", "Aggregator"), ("https://remoteok.com/x", "Aggregator"),
    ("https://careers.acme.io/apply/12", "Direct (no login)"), ("", "Aggregator"),
])
def test_apply_method(url, expected):
    assert apply_method(url, CFG) == expected


def test_merge_duplicates_prefers_direct_and_unions_countries():
    a = classify(job("AI Engineer", "Berlin", description="Visa sponsorship.", source="arbeitnow",
                     url="https://www.arbeitnow.com/jobs/a"), CFG)
    b = classify(job("AI Engineer", "Stockholm", description="Visa sponsorship."), CFG)
    (row,) = merge_duplicates([a, b])
    assert row["Apply method"] == "Direct (no login)" and "arbeitnow" in row["Source"]
    assert set(row["Country"].split(" / ")) == {"Germany", "Sweden"} and row["Nordic"] == "Yes"


# ---- sources
def test_parse_relocate_skips_ads_and_reads_country_from_path():
    html = ('<div class="job__title"><a href="/netherlands/amsterdam/catawiki/senior-product-manager-demand-10278">'
            '<b>Product Manager - Demand</b></a></div>'
            '<div class="job__title"><a href="/remote/remote/the-global-move/1700-curated-10080"><b>Ad</b></a></div>')
    (j,) = parse_relocate(html)
    assert (j.company, j.title, j.location) == ("Catawiki", "Product Manager - Demand", "Amsterdam, Netherlands")
    assert classify(j, CFG, hint="relocation")["Visa/Relocation"] == "relocation"


def test_arbeitnow_job_gets_default_country_for_unknown_city():
    j = europe._arbeitnow_job({"company_name": "Foo", "title": "Backend Engineer", "location": "Bremen", "url": "https://www.arbeitnow.com/x",
                               "created_at": 1790000000, "description": "<p>hi</p>", "remote": False}, "Germany")
    assert j.location == "Bremen, Germany" and j.posted_at is not None


def test_personio_teamtailor_recruitee_parsers(monkeypatch):
    class Resp:
        def __init__(self, content=b"", data=None, url=""):
            self.content, self._data, self.url = content, data, url
        def json(self):
            return self._data
    personio_xml = b"""<workzag-jobs><position><id>7</id><office>Stockholm</office><name>Backend Engineer</name>
        <createdAt>2026-10-01T10:00:00+00:00</createdAt><jobDescriptions><jobDescription><name>Offer</name>
        <value>&lt;p&gt;Relocation support&lt;/p&gt;</value></jobDescription></jobDescriptions></position></workzag-jobs>"""
    monkeypatch.setattr(europe_ats, "_get", lambda url, **kw: Resp(personio_xml, url="https://acme.jobs.personio.de/xml?language=en"))
    (p,) = europe_ats.personio("Acme", "acme")
    assert p.url == "https://acme.jobs.personio.de/job/7" and "Relocation support" in p.description and p.location == "Stockholm"

    rss = b"""<rss xmlns:tt="https://teamtailor.com/locations"><channel><item><title>PM</title><link>https://acme.teamtailor.com/jobs/1</link>
        <pubDate>Mon, 05 Oct 2026 10:00:00 +0000</pubDate><description>Visa sponsorship</description>
        <tt:locations><tt:location><tt:city>Oslo</tt:city><tt:country>Norway</tt:country></tt:location></tt:locations></item></channel></rss>"""
    monkeypatch.setattr(europe_ats, "_get", lambda url, **kw: Resp(rss))
    (t,) = europe_ats.teamtailor("Acme", "acme")
    assert t.location == "Oslo, Norway" and t.title == "PM"

    monkeypatch.setattr(europe_ats, "_json", lambda url: {"offers": [{"title": "Dev", "careers_url": "https://acme.recruitee.com/o/dev",
                                                                       "location": "Amsterdam, Netherlands", "remote": False, "status": "published",
                                                                       "description": "<b>Blue Card</b>"}]})
    (r,) = europe_ats.recruitee("Acme", "acme")
    assert r.location == "Amsterdam, Netherlands" and r.description == "Blue Card"


# ---- sheet merge
def fresh_row(i, score=80, **kw):
    base = {"ID": i, "Score": score, "Company": f"Co{i}", "Role": "AI Engineer", "Family": "Engineering", "AI": "Yes",
            "Country": "Sweden", "Nordic": "Yes", "Visa/Relocation": "sponsor", "Remote": "No",
            "Apply method": "Direct (no login)", "Apply link": f"https://x/{i}", "Why": "w", "Posted": "2026-10-10",
            "Source": "greenhouse"}
    base.update(kw)
    return base


def test_new_rows_default_status_and_first_seen():
    (row,) = europe_sheet.merge([], [fresh_row("a")], "2026-10-15")
    assert (row["Status"], row["First seen"], row["Last seen"], row["Open"]) == ("New", "2026-10-15", "2026-10-15", "Yes")


def test_status_notes_and_user_columns_survive():
    existing = [{"ID": "a", "Status": "Applied", "Notes": "referral", "First seen": "2026-10-01", "Open": "Yes",
                 "Last seen": "2026-10-14", "Score": "70", "My col": "x"}]
    (row,) = europe_sheet.merge(existing, [fresh_row("a", 91)], "2026-10-15")
    assert (row["Status"], row["Notes"], row["My col"], row["First seen"], row["Score"]) == ("Applied", "referral", "x", "2026-10-01", 91)


def test_vanished_rows_flagged_or_pruned():
    existing = [
        {"ID": "tracked", "Status": "Shortlisted", "Last seen": "2026-09-01", "Open": "Yes", "Source": "greenhouse", "Score": "60"},
        {"ID": "stale", "Status": "New", "Last seen": "2026-09-01", "Open": "Yes", "Source": "greenhouse", "Score": "60"},
        {"ID": "recent", "Status": "New", "Last seen": "2026-10-14", "Open": "Yes", "Source": "greenhouse", "Score": "60"},
        {"ID": "other-source", "Status": "New", "Last seen": "2026-09-01", "Open": "Yes", "Source": "relocate.me", "Score": "60"},
    ]
    rows = {r["ID"]: r for r in europe_sheet.merge(existing, [fresh_row("a")], "2026-10-15", scanned={"ats"})}
    assert rows["tracked"]["Open"] == "No" and "stale" not in rows and rows["recent"]["Open"] == "No"
    assert rows["other-source"]["Open"] == "Yes"  # its source did not answer this run


def test_sorted_open_first_then_score():
    existing = [{"ID": "gone", "Status": "Applied", "Last seen": "2026-10-01", "Open": "Yes", "Source": "ats", "Score": "99"}]
    rows = europe_sheet.merge(existing, [fresh_row("lo", 50), fresh_row("hi", 90)], "2026-10-15", scanned={"ats"})
    assert [r["ID"] for r in rows] == ["hi", "lo", "gone"]


def test_to_values_escapes_formulas_and_keeps_ids_text():
    header = europe_sheet.COLUMNS
    (row,) = europe_sheet.merge([], [fresh_row("12e4", Company="=HYPERLINK(\"evil\")", Role="+cmd")], "2026-10-15")
    got = dict(zip(header, europe_sheet.to_values(header, [row])[1]))
    assert got["Company"].startswith("'=") and got["Role"].startswith("'+")
    assert got["ID"] == "'12e4" and got["First seen"] == "'2026-10-15" and got["Score"] == 80
    assert europe_sheet.COLUMNS[:3] == ["Score", "Company", "Role"] and "Apply method" in europe_sheet.COLUMNS


def test_summary_highlights_nordics():
    rows = europe_sheet.merge([], [fresh_row("a"), fresh_row("b", Country="Germany", Nordic="No", Family="Product")], "2026-10-15")
    text = europe_sheet.summarize(rows)
    assert "NORDICS: Sweden 1" in text and "Germany 1" in text and "Product 1" in text
