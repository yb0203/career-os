from datetime import datetime, timedelta, timezone

import pytest
import yaml

from pipeline import gates, scorer
from pipeline.models import Job
from pipeline.run import ROOT

CFG = yaml.safe_load((ROOT / "config/lanes.yaml").read_text())


def job(title="Product Manager", location="Bangalore", days=2, desc="", remote=None, etype=""):
    return Job(
        company="Acme", title=title, url="https://x", source="lever", location=location,
        remote=remote, posted_at=datetime.now(timezone.utc) - timedelta(days=days),
        description=desc, employment_type=etype,
    )


@pytest.mark.parametrize("title,lane", [
    ("Founder's Office Associate", "growth_strategy"),
    ("Strategy & Operations Manager", "growth_strategy"),
    ("Product Manager II", "ai_pm"),
    ("Technical Program Manager", "ai_pm"),
    ("Fractional Product Manager", "fractional"),
    ("Director of Product", None),
    ("Software Engineer, Growth", None),
    ("Growth Marketer", None),
    ("Head of Strategy", None),
])
def test_lane_classification(title, lane):
    assert gates.classify_lane(job(title=title), CFG) == lane


def test_contract_employment_type_routes_to_fractional():
    assert gates.classify_lane(job(etype="Contract"), CFG) == "fractional"


@pytest.mark.parametrize("location,remote,ok", [
    ("Bengaluru, India", None, True),
    ("Remote, Global", True, True),
    ("Remote", True, True),
    ("Remote - US", True, False),
    ("United States / United Kingdom", True, False),
    ("USA - TN - Remote", True, False),
    ("San Francisco, CA", False, False),
])
def test_location_gate(location, remote, ok):
    assert gates.location_ok(job(location=location, remote=remote), CFG["gates"])[0] is ok


def test_region_block_in_description():
    j = job(location="Remote", remote=True, desc="Applicants must be based in the US.")
    assert gates.location_ok(j, CFG["gates"])[0] is False


def test_stale_and_overleveled_jobs_dropped():
    assert gates.apply(job(days=30), CFG) is False
    assert gates.apply(job(desc="8+ years of product management experience"), CFG) is False
    assert gates.apply(job(desc="2-4 years of experience in product"), CFG) is True


@pytest.mark.parametrize("text,years", [
    ("6+ years of total experience, including 3–4 years in PM", 6),
    ("2–4 years of experience in Product Management", 2),
    ("3+ years of experience; 5+ years preferred", 3),
    ("We have 10 years of history", None),
    ("Experience: 2–3 years in a Founder's Office", 2),
    ("Work experience required: 4 - 9 Years", 4),
    ("3-5 years of experience", 3),
    ("Founded 10 years ago. You bring 2+ years of experience in growth.", 2),
    ("Nice to have: 7+ years of experience in fintech", None),
    ("5+ years preferred, 3+ years of relevant experience required", 3),
    ("Must-haves:\n• 2–4 years of experience in Product Management, preferably in FinTech", 2),
    ("4+ years of experience, ideally in B2B SaaS", 4),
    ("3+ years of experience. 6+ years of experience is a plus.", 3),
])
def test_min_years_required(text, years):
    assert gates.min_years_required(text) == years


def test_total_experience_beats_smaller_sub_requirement_at_gate():
    desc = "6+ years of total experience, including 3–4 years in product management"
    assert gates.apply(job(desc=desc), CFG) is False


def test_undated_job_never_p0():
    j = job(desc="LLM agents for payments in fintech")
    j.posted_at = None
    assert scorer.score(j, CFG).priority != "P0"


def test_dedupe_prefers_ats_copy():
    from pipeline.run import dedupe
    li = job(title="Product Manager II")
    li.source = "linkedin"
    ats = job(title="Product Manager II", desc="full JD")
    ats.source = "lever"
    kept = dedupe([li, ats])
    assert len(kept) == 1 and kept[0].source == "lever"
    assert "also on linkedin" in kept[0].reasons


def test_score_bands():
    fresh_blr = scorer.score(job(desc="LLM agents for payments"), CFG)
    assert fresh_blr.score >= CFG["scoring"]["p0"] and fresh_blr.priority == "P0"
    stale_remote = scorer.score(job(location="Remote", remote=True, days=12,
                                    title="Senior Product Manager",
                                    desc="5 years of experience"), CFG)
    assert stale_remote.score < fresh_blr.score
    assert stale_remote.priority == "P2"


@pytest.mark.parametrize("url,source,via", [
    ("https://jobs.lever.co/acme/1", "getro:jobs.accel.com", "lever"),
    ("https://jobs.ashbyhq.com/acme/1", "consider:jobs.sequoiacap.com", "ashby"),
    ("https://www.linkedin.com/jobs/view/123", "linkedin", "linkedin"),
    ("https://cutshort.io/job/x", "cutshort", "cutshort"),
    ("https://www.instahyre.com/job-1-pm", "instahyre", "instahyre"),
    ("https://weworkremotely.com/remote-jobs/x", "weworkremotely", "weworkremotely"),
    ("https://careers.acme.co.in/pm", "getro:jobs.accel.com", "acme"),
    ("", "getro:jobs.accel.com", "getro"),
])
def test_apply_via_derived_from_posting_url(url, source, via):
    assert Job(company="A", title="PM", url=url, source=source).apply_via == via


def test_apply_via_explicit_value_wins_and_lands_in_csv_row():
    j = Job(company="A", title="PM", url="https://jobs.lever.co/a/1", source="lever", apply_via="lever")
    assert j.to_row()["apply_via"] == "lever"
