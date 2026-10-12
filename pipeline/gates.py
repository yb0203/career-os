"""Hard gates. A job that fails any gate is dropped before scoring."""
from __future__ import annotations

import re
from typing import Optional

from pipeline.models import Job

YEARS_RE = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*years?", re.I)


def classify_lane(job: Job, cfg: dict) -> Optional[str]:
    title = f" {job.title.lower()} "
    if any(x in title for x in cfg["exclude_titles"]):
        return None
    lanes = cfg["lanes"]
    etype = job.employment_type.lower()
    frac = lanes["fractional"]
    if any(t in title for t in frac["titles"]) or any(t == etype for t in frac["employment_types"]):
        # Fractional only counts if the function also matches another lane
        if any(t in title for lane in ("growth_strategy", "ai_pm") for t in lanes[lane]["titles"]):
            return "fractional"
    for lane in ("growth_strategy", "ai_pm"):
        if any(t in title for t in lanes[lane]["titles"]):
            return lane
    return None


def min_years_required(text: str) -> Optional[int]:
    """Smallest 'N years' figure mentioned near experience, e.g. '3-5 years' -> 3."""
    found = [
        int(m.group(1))
        for m in YEARS_RE.finditer(text)
        if "experience" in text[m.start(): m.end() + 60].lower()
    ]
    return min(found) if found else None


def location_ok(job: Job, gates: dict) -> tuple[bool, str]:
    loc = job.location.lower()
    desc = job.description.lower()
    if any(b in desc or b in loc for b in gates["remote_region_block"]):
        return False, "remote restricted to another region"
    if any(a in loc for a in gates["location_allow"]):
        return True, "location match"
    # Whatever is left after removing "remote" words names a region; if it names
    # anywhere at all (and none of it is allowed), the role is out of reach.
    places = re.sub(r"\b(fully|100%|remote|hybrid|or|within|based|office)\b", " ", loc)
    places = re.sub(r"[^a-z]+", " ", places).strip()
    if (job.remote or "remote" in loc) and not places:
        return True, "remote, region unspecified"
    return False, f"location {job.location or 'unknown'}"


def apply(job: Job, cfg: dict) -> bool:
    gates = cfg["gates"]
    lane = classify_lane(job, cfg)
    if not lane:
        return False
    job.lane = lane

    age = job.age_days
    if age is not None and age > gates["max_age_days"]:
        return False

    ok, why = location_ok(job, gates)
    if not ok:
        return False
    job.reasons.append(why)

    years = min_years_required(job.description)
    if years is not None and years > gates["max_years_experience"]:
        return False
    if years is not None:
        job.reasons.append(f"{years}+ yrs asked")
    return True
