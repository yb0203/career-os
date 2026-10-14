"""Auto-tier new openings (Strong / Medium / Exploratory / Skip) per Yashvi's role scope (job-applications/ROLE_SCOPE.md).

Only fills rows whose Tier is empty and Status is New, so hand-set tiers always win.
Called from `python -m pipeline.queue`, i.e. after every daily sync.

  Strong       core PM-type role, not senior, Bengaluru/remote-India, asks <= 4 yrs (or unstated)
  Medium       core role that is senior (asks <= 6 yrs) or based in Gurugram/Noida/Delhi
  Exploratory  adjacent role (growth, ops, strategy, solutions, ...), contract/part-time/internship/fresher
               roles, or a big experience stretch
  Skip         only in Mumbai/Pune/Hyderabad/Chennai/other cities (no Bengaluru, NCR or remote), or a hard-no
               function (pure marketing/content, engineering/data-science only, support/recruiting/admin)
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
NCR = re.compile(r"gurgaon|gurugram|noida|delhi|ncr\b|faridabad|ghaziabad", re.I)
# Only counts as out of scope when no Bengaluru / remote / NCR option is listed alongside.
OTHER_CITY = re.compile(r"mumbai|pune|hyderabad|chennai|kolkata|ahmedabad|jaipur|kochi|thiruvananthapuram|"
                        r"trivandrum|indore|chandigarh|lucknow|coimbatore|nagpur|vadodara|surat|bhubaneswar", re.I)
FLEX = re.compile(r"contract|freelance|fractional|part[- ]?time|intern\b|internship|fresher|entry[- ]level|graduate", re.I)
HARD_NO = re.compile(r"marketing manager|content (writer|marketer|strategist|creator)|social media|copywriter|\bseo\b|"
                     r"software (development )?engineer|data scientist|machine learning engineer|\bml engineer|"
                     r"(backend|frontend|front-end|back-end|full[- ]?stack|devops|qa|sdet) engineer|"
                     r"customer support|support (specialist|engineer|executive|associate)|recruiter|talent acquisition|"
                     r"hr (business partner|manager|generalist|executive)|office (admin|manager)|administrator", re.I)
YEARS = re.compile(r"(\d{1,2})\+? yrs asked")


def years_asked(why: str) -> Optional[int]:
    m = YEARS.search(why or "")
    return int(m.group(1)) if m else None


def classify(role: str, location: str, why: str = "") -> str:
    if HARD_NO.search(role):
        return "Skip"
    remote = bool(re.search(r"remote|anywhere|worldwide|work from home|\bwfh\b", location, re.I))
    home = remote or bool(re.search(r"bengaluru|bangalore", location, re.I)) or (
        bool(HOME.search(location)) and not OTHER_INDIA.search(location))
    ncr = bool(NCR.search(location))
    if not home and not ncr and OTHER_CITY.search(location):
        return "Skip"
    if FLEX.search(role) or FLEX.search(why or ""):
        return "Exploratory"
    years = years_asked(why)
    if not CORE.search(role):
        return "Exploratory"
    if VERY_SENIOR.search(role) or (years is not None and years > 6):
        return "Exploratory"
    if SENIOR.search(role) or (years is not None and years > 4) or not home:
        return "Medium"
    return "Strong"


def fill_tiers(rows: list[dict]) -> dict[str, str]:
    """Return {ID: tier} for New rows that have no tier yet."""
    return {r["ID"]: classify(r.get("Role", ""), str(r.get("Location", "")), str(r.get("Why", "")))
            for r in rows if r.get("ID") and r.get("Status") == "New" and not r.get("Tier")}
