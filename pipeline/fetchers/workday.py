"""Workday career sites (public CXS JSON API, no login): Mastercard, Barclays, Citi, Nasdaq, PayPal, ...

slug = "<host-prefix>|<tenant>|<site>", e.g. "mastercard.wd1|mastercard|CorporateCareers"
(host-prefix + ".myworkdayjobs.com"; the site is the path segment of the public careers URL).
Only India and remote-looking postings whose title looks like product/growth/program work are kept, and their
description is fetched so the years asked can be read. Added 2026-10-29 ("add the recommended job portals").
"""
from __future__ import annotations

import re

import requests

from pipeline import fetchers as f
from pipeline.models import Job

QUERIES = ["product manager", "product owner", "associate product manager", "growth", "technical program manager"]
INDIA = re.compile(r"india|bengaluru|bangalore|gurugram|gurgaon|noida|delhi|hyderabad|pune|mumbai|chennai|remote", re.I)
TITLE = re.compile(r"product (manager|owner|lead|management)|associate product|\bapm\b|growth|program manager|founder|chief of staff", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"}


def parse_listing(host: str, site: str, posting: dict) -> dict | None:
    """Pick the fields we need from one CXS jobPostings entry; None when it is not India/remote product-like."""
    title, where = posting.get("title", ""), posting.get("locationsText", "")
    path = posting.get("externalPath", "")
    if not (title and path and INDIA.search(where) and TITLE.search(title)):
        return None
    return {"title": title, "location": where, "path": path, "url": f"https://{host}.myworkdayjobs.com/{site}{path}",
            "posted": posting.get("postedOn", "")}


def fetch(company: str, slug: str) -> list[Job]:
    prefix, tenant, site = slug.split("|")
    host = f"{prefix}.myworkdayjobs.com"
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    found: dict[str, dict] = {}
    for q in QUERIES:
        for offset in (0, 20, 40):
            r = requests.post(f"{api}/jobs", headers=HEADERS, timeout=f.TIMEOUT,
                              json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q})
            if r.status_code != 200:
                break
            postings = r.json().get("jobPostings", [])
            for p in postings:
                item = parse_listing(prefix, site, p)
                if item:
                    found[item["path"]] = item
            if len(postings) < 20:
                break
    jobs = []
    for item in found.values():
        desc, posted = "", None
        try:
            info = requests.get(f"{api}{item['path']}", headers=HEADERS, timeout=f.TIMEOUT).json().get("jobPostingInfo", {})
            desc = f.strip_html(info.get("jobDescription", ""))
            posted = f.parse_iso(info.get("startDate"))
        except Exception:
            pass
        jobs.append(Job(company=company, title=item["title"], url=item["url"], source="workday", apply_via="workday",
                        location=item["location"], remote=True if re.search("remote", item["location"], re.I) else None,
                        posted_at=posted, description=desc))
    return jobs
