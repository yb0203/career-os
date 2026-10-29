"""India-focused sources: LinkedIn public search, Instahyre, Cutshort."""
from __future__ import annotations

import html
import re
import time

from pipeline.fetchers import parse_iso, strip_html
from pipeline.models import Job
from pipeline.sources import find_list, next_data, session

LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_CARD = re.compile(
    r'base-card__full-link[^>]*href="(?P<url>[^"?]+)[^>]*>.*?'
    r'base-search-card__title">\s*(?P<title>.*?)\s*</h3>.*?'
    r'base-search-card__subtitle">.*?>\s*(?P<company>[^<]+?)\s*<.*?'
    r'job-search-card__location">\s*(?P<location>.*?)\s*</span>.*?'
    r'datetime="(?P<date>[\d-]+)"',
    re.S,
)


def linkedin(params, terms):
    """Public guest search, posted in the past 7 days.

    From shared cloud IPs LinkedIn answers 429 after a few requests, so each request waits a randomised moment and a
    429 is retried after a growing pause (up to `retries` times per page) instead of ending the whole source.
    Raises only if nothing could be fetched at all."""
    import random
    s, jobs, seen = session(), [], set()
    retries, pause = params.get("retries", 4), params.get("backoff_seconds", 45)
    blocked = False
    for term in terms:
        for loc in params.get("locations", ["India"]):
            for page in range(params.get("pages", 1)):
                r = None
                for attempt in range(retries + 1):
                    r = s.get(LI_SEARCH, timeout=30, params={
                        "keywords": term, "location": loc, "f_TPR": "r604800", "start": page * 25})
                    if r.status_code != 429:
                        break
                    if attempt < retries:
                        time.sleep(pause * (attempt + 1) + random.uniform(0, 10))
                if r.status_code == 429:   # still blocked after the retries: keep what we have
                    blocked = True
                    break
                if r.status_code != 200 or not r.text.strip():
                    break
                for m in LI_CARD.finditer(r.text):
                    if m["url"] in seen:
                        continue
                    seen.add(m["url"])
                    jobs.append(Job(
                        company=html.unescape(m["company"]), title=html.unescape(m["title"]),
                        url=m["url"], source="linkedin", location=html.unescape(m["location"]),
                        remote="remote" in m["location"].lower() or None,
                        posted_at=parse_iso(m["date"]),
                    ))
                time.sleep(random.uniform(2.0, 4.5))
            if blocked:
                blocked = False   # try the next term/location; the block may be per-query
    if not jobs:
        raise RuntimeError("rate-limited by LinkedIn; try again in a few hours")
    return jobs


def instahyre(params, terms):
    s, jobs = session(), []
    for fn in params.get("job_functions", [11]):
        for page in range(params.get("pages", 5)):
            data = s.get("https://www.instahyre.com/api/v1/job_search", timeout=30, params={
                "job_functions": fn, "limit": 35, "offset": page * 35}).json()
            for j in data.get("objects", []):
                emp = j.get("employer") or {}
                jobs.append(Job(
                    company=emp.get("company_name", ""), title=j.get("title", ""),
                    url=j.get("public_url", ""), source="instahyre", location=j.get("locations", ""),
                    remote="work from home" in (j.get("locations") or "").lower() or None,
                    description=" ".join(j.get("keywords") or []),
                ))
            if not data.get("meta", {}).get("next"):
                break
    return jobs


def cutshort(params, terms):
    s, jobs = session(), []
    for slug in params.get("pages", []):
        raw = find_list(next_data(s.get(f"https://cutshort.io/jobs/{slug}", timeout=30).text), "jobs") or []
        for j in raw:
            exp = j.get("expRange") or {}
            locs = j.get("locations") or []
            desc = strip_html(j.get("sanitizedComment", ""))
            if exp.get("min") is not None:
                desc = f"{exp['min']}-{exp.get('max', '')} years of experience. " + desc
            jobs.append(Job(
                company=(j.get("companyDetails") or {}).get("name", ""), title=j.get("headline", ""),
                url=j.get("publicUrl", ""), source="cutshort", location=" / ".join(locs),
                remote=any("remote" in x.lower() for x in locs) or None, description=desc,
            ))
    return jobs
