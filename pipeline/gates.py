"""Hard gates. A job that fails any gate is dropped before scoring."""
from __future__ import annotations

import re
from typing import Optional

from pipeline.models import Job

YEARS_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b", re.I)
WINDOW = 60  # chars of context either side of a "N years" mention
# Trailing cue must sit in the same short clause ("5+ years preferred"); "preferably in
# FinTech" qualifies the domain, not the years, so it doesn't count.
PREFERRED_AFTER = re.compile(r"preferred|nice[- ]to[- ]have|bonus|is a plus|an advantage|desirable", re.I)
TRAILING_CUE_WINDOW = 30
PREFERRED_BEFORE = re.compile(
    r"preferred\s*(?:qualifications|requirements|skills|experience)?\s*:|preferred qualifications"
    r"|nice[- ]to[- ]haves?|bonus|ideally", re.I)


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


def _clip_before(text: str, start: int) -> str:
    """Up to WINDOW chars before `start`, cut at the last sentence/clause break."""
    chunk = text[max(0, start - WINDOW): start]
    return re.split(r"[.;]\s", chunk)[-1]


def _clip_after(text: str, end: int, stop: int) -> str:
    """Up to WINDOW chars after `end` (never past `stop`), cut at the first sentence/clause break."""
    chunk = text[end: min(end + WINDOW, stop)]
    return re.split(r"[.;](?:\s|$)", chunk)[0]


def min_years_required(text: str) -> Optional[int]:
    """Years of experience a JD requires, e.g. '6+ years total, incl. 3-4 in PM' -> 6.

    Takes the largest required lower bound ('2-4 years' counts as 2) among mentions tied to
    the word 'experience', skipping ones flagged as preferred / nice to have / bonus.
    """
    matches = list(YEARS_RE.finditer(text))
    found = []
    for i, m in enumerate(matches):
        nxt = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = _clip_before(text, m.start()).lower()
        after = _clip_after(text, m.end(), len(text)).lower()
        if "experience" not in before + " " + after:
            continue  # e.g. "founded 10 years ago"
        # A trailing cue ("5+ years preferred") only belongs to this mention if no other
        # mention sits in between; a leading cue must look like a lead-in ("Nice to have:").
        trailing = re.split(r"[,•\n]", _clip_after(text, m.end(), min(nxt, m.end() + TRAILING_CUE_WINDOW)))[0]
        if PREFERRED_AFTER.search(trailing) or PREFERRED_BEFORE.search(before):
            continue
        found.append(int(m.group(1)))
    return max(found) if found else None


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
