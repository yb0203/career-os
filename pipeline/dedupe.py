"""Duplicate-job detection so counts are true (Yashvi, 2026-10-29: "don't add duplicate jobs, that will give a false count").

The stable job ID only matches identical company+title text, so the same job listed as "Branch International Inc." and
"Branch International", or with a "(Bengaluru)" suffix, or on LinkedIn and on the company's own ATS, got two rows.
`canon_key` collapses those. It deliberately keeps team/product words ("Product Manager - Credit" vs "- Investments"),
seniority ("Senior ..."), and the level numeral only when it is part of the title ("Product Manager II" stays distinct).
"""
from __future__ import annotations

import re
from collections import defaultdict

_SUFFIX = re.compile(r"\b(inc|incorporated|ltd|limited|pvt|private|llp|llc|corp|corporation|co|gmbh|ag|sa|plc)\b", re.I)
_FILLER = re.compile(r"\b(the|technologies|technology|software|services|solutions|labs|group|india)\b", re.I)
_CITY_TAIL = re.compile(
    r"\s*[-–|,@]\s*(bengaluru|bangalore|gurgaon|gurugram|noida|delhi|new delhi|mumbai|pune|hyderabad|chennai|india|remote|"
    r"karnataka|haryana|worldwide|hybrid|on-?site)\b.*$", re.I)


# Bracketed text that never distinguishes two roles: gender tags, work mode, locations.
_NOISE_TAG = re.compile(
    r"(?:[mfwdx]\s*/\s*){1,3}[mfwdx]|remote|hybrid|on-?site|full[- ]?time|contract|permanent|"
    r"(?:india|bengaluru|bangalore|gurugram|gurgaon|noida|delhi|new delhi|mumbai|pune|hyderabad|chennai|worldwide|global|"
    r"uk|eu|emea|apac|us|usa|london|berlin|amsterdam|paris)(?:\s*[,/&-]\s*\w+)*(?:\s*[-–]\s*remote)?", re.I)


def norm_company(c: str) -> str:
    c = re.sub(r"\(.*?\)", "", str(c).lower())
    c = _FILLER.sub(" ", _SUFFIX.sub(" ", c))
    return re.sub(r"[^a-z0-9]", "", c)


def norm_title(t: str) -> str:
    t = str(t).lower()
    t = re.sub(r"[\(\[]([^)\]]*)[\)\]]", lambda m: " " if _NOISE_TAG.fullmatch(m.group(1).strip()) else f" {m.group(1)} ", t)
    t = _CITY_TAIL.sub("", t)                         # trailing "- Bengaluru", ", India"
    t = re.sub(r"\bsr\.?\b", "senior", t)
    t = re.sub(r"\bassoc\.?\b", "associate", t)
    return re.sub(r"[^a-z0-9]", "", t)


def canon_key(company: str, title: str) -> tuple[str, str]:
    return norm_company(company), norm_title(title)


STATUS_RANK = {"Interviewing": 0, "Offer": 0, "Rejected": 1, "Applied": 2, "In Progress": 3, "Closed": 4, "New": 5, "": 5, "Skip": 6}
DIRECT = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "careers-page", "workday", "keka", "kula", "applytojob")


def keeper_rank(row: dict) -> tuple:
    src = str(row.get("Source", "")).lower()
    return (STATUS_RANK.get(row.get("Status", ""), 5), 0 if any(d in src for d in DIRECT) else 1,
            str(row.get("First seen", "9999")))


def find_duplicates(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    """[(keeper, [duplicates...])] for every company+title group with more than one row."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("Company") and r.get("Role"):
            groups[canon_key(r["Company"], r["Role"])].append(r)
    out = []
    for g in groups.values():
        if len(g) > 1:
            g = sorted(g, key=keeper_rank)
            out.append((g[0], g[1:]))
    return out


def plan_updates(rows: list[dict]) -> dict[str, tuple[str, str]]:
    """{ID: (new Status, note)} that marks every extra copy of a job as a duplicate (Status Skip).

    The keeper is the most advanced row (Interviewing > Rejected > Applied > In Progress > New), then a direct ATS
    row, then the oldest. Rows already Skip are left alone, and a keeper is never changed."""
    plan: dict[str, tuple[str, str]] = {}
    for keeper, dups in find_duplicates(rows):
        for d in dups:
            if d.get("Status") == "Skip" or not d.get("ID"):
                continue
            old = str(d.get("Notes", ""))[:100]
            plan[d["ID"]] = ("Skip", f"Duplicate of {keeper.get('Company', '')} / {keeper.get('Role', '')} "
                                     f"({keeper.get('Source', '')}, {keeper.get('Status', '') or 'New'}); was {d.get('Status') or 'New'}"
                                     + (f" | {old}" if old else ""))
    return plan
