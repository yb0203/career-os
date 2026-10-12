"""0-100 fit score for jobs that passed the gates.

lane 35 · exact-title bonus 5 · location 20 · freshness 15 · seniority 15 · keywords 10

P0 means "apply today": fresh, reachable location, target title. Postings with no date
or no description can't prove freshness/seniority, so they top out around P1.
"""
from __future__ import annotations

from pipeline.gates import min_years_required
from pipeline.models import Job

STRONG_TITLES = (
    "founder's office", "founders office", "chief of staff", "associate product manager",
    "ai product manager", "product manager", "strategy & operations", "strategy and operations",
    "business operations", "deployment strategist", "technical program manager",
)
SENIOR_WORDS = ("senior", "sr.", "sr ", "lead", "leader")


def score(job: Job, cfg: dict) -> Job:
    s = 35  # passed the lane gate
    title = job.title.lower()
    if any(t in title for t in STRONG_TITLES):
        s += 5

    loc = job.location.lower()
    if any(x in loc for x in ("bangalore", "bengaluru")) or "india" in loc:
        s += 20
    elif any(x in loc for x in ("anywhere", "worldwide", "global", "apac", "asia")):
        s += 18
    else:
        s += 8  # remote, region unspecified — verify before applying

    age = job.age_days
    if age is None:
        job.reasons.append("post date unknown")
    elif age <= 3:
        s += 15
    elif age <= 7:
        s += 10
    else:
        s += 5

    years = min_years_required(job.description)
    if not job.description.strip():
        s += 8  # can't tell
    elif years is None or years <= 3:
        s += 15
    elif years <= 5:
        s += 8

    if any(w in title for w in SENIOR_WORDS):
        s -= 10  # reachable at ~3 yrs, but a stretch
        job.reasons.append("senior title: stretch")

    desc = job.description.lower()
    hits = [k for k in cfg["scoring"]["keywords"] if k in desc]
    s += min(10, 2 * len(hits))
    if hits:
        job.reasons.append("keywords: " + ", ".join(hits[:5]))

    if age is None:
        s = min(s, cfg["scoring"]["p0"] - 1)  # freshness unproven: never P0
    job.score = max(0, min(100, s))
    sc = cfg["scoring"]
    job.priority = "P0" if job.score >= sc["p0"] else "P1" if job.score >= sc["p1"] else "P2"
    return job
