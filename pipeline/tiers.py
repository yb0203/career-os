"""Auto-tier new openings (Strong / Medium / Exploratory) with the rubric we apply by hand.

Only fills rows whose Tier is empty and Status is New, so hand-set tiers always win.
Called from `python -m pipeline.queue`, i.e. after every daily sync.

  Strong       core PM-type role, not senior, Bengaluru/remote-India, asks <= 4 yrs (or unstated)
  Medium       core role that is senior (asks <= 6 yrs) or in another Indian city
  Exploratory  adjacent role (growth, ops, strategy, solutions, forward-deployed, ...) or a big stretch
"""
from __future__ import annotations

import re
from typing import Optional

CORE = re.compile(r"product (manager|owner|lead)|\bapm\b|associate product|technical program|\btpm\b|"
                  r"program manager|founder'?s office|chief of staff", re.I)
ADJACENT = re.compile(r"growth|strateg|operations|\bops\b|solutions?|forward deployed|business analyst|"
                      r"revenue|implementation|analyst|producer|specialist", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head|director|vp|group)\b", re.I)
VERY_SENIOR = re.compile(r"\b(principal|staff|head|director|vp|group)\b", re.I)
HOME = re.compile(r"bengaluru|bangalore|remote|anywhere|work from home|\bindia\b", re.I)
OTHER_INDIA = re.compile(r"gurgaon|gurugram|noida|delhi|mumbai|pune|hyderabad|chennai|kolkata|ahmedabad|"
                         r"jaipur|kochi|thiruvananthapuram|trivandrum|indore|chandigarh|lucknow", re.I)
YEARS = re.compile(r"(\d{1,2})\+? yrs asked")


def years_asked(why: str) -> Optional[int]:
    m = YEARS.search(why or "")
    return int(m.group(1)) if m else None


def classify(role: str, location: str, why: str = "") -> str:
    years = years_asked(why)
    if not CORE.search(role):
        return "Exploratory"
    if VERY_SENIOR.search(role) or (years is not None and years > 6):
        return "Exploratory"
    in_bengaluru = bool(re.search(r"bengaluru|bangalore", location, re.I))
    home = in_bengaluru or (HOME.search(location) and not OTHER_INDIA.search(location))
    if SENIOR.search(role) or (years is not None and years > 4) or not home:
        return "Medium"
    return "Strong"


def fill_tiers(rows: list[dict]) -> dict[str, str]:
    """Return {ID: tier} for New rows that have no tier yet."""
    return {r["ID"]: classify(r.get("Role", ""), str(r.get("Location", "")), str(r.get("Why", "")))
            for r in rows if r.get("ID") and r.get("Status") == "New" and not r.get("Tier")}
