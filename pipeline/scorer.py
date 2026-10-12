"""0-100 fit score for jobs that passed the gates.

title/lane 40 · location 20 · freshness 15 · seniority 15 · keywords 10
"""
from __future__ import annotations

from pipeline.gates import min_years_required
from pipeline.models import Job


def score(job: Job, cfg: dict) -> Job:
    s = 40  # passed the lane gate

    loc = job.location.lower()
    if any(x in loc for x in ("bangalore", "bengaluru")) or "india" in loc:
        s += 20
    elif any(x in loc for x in ("anywhere", "worldwide", "global", "apac", "asia")):
        s += 18
    else:
        s += 8  # remote, region unspecified — verify before applying

    age = job.age_days
    if age is None:
        s += 5
    elif age <= 3:
        s += 15
    elif age <= 7:
        s += 10
    else:
        s += 5

    years = min_years_required(job.description)
    if years is None or years <= 3:
        s += 15
    elif years <= 5:
        s += 8

    if "senior" in job.title.lower() or "sr." in job.title.lower():
        s -= 10  # reachable at ~3 yrs, but a stretch
        job.reasons.append("senior title: stretch")

    desc = job.description.lower()
    hits = [k for k in cfg["scoring"]["keywords"] if k in desc]
    s += min(10, 2 * len(hits))
    if hits:
        job.reasons.append("keywords: " + ", ".join(hits[:5]))

    job.score = min(100, s)
    sc = cfg["scoring"]
    job.priority = "P0" if job.score >= sc["p0"] else "P1" if job.score >= sc["p1"] else "P2"
    return job
