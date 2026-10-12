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


def test_min_years_required():
    assert gates.min_years_required("3-5 years of experience") == 3
    assert gates.min_years_required("We have 10 years of history") is None


def test_score_bands():
    fresh_blr = scorer.score(job(desc="LLM agents for payments"), CFG)
    assert fresh_blr.score >= CFG["scoring"]["p0"] and fresh_blr.priority == "P0"
    stale_remote = scorer.score(job(location="Remote", remote=True, days=12,
                                    title="Senior Product Manager",
                                    desc="5 years of experience"), CFG)
    assert stale_remote.score < fresh_blr.score
    assert stale_remote.priority == "P2"
