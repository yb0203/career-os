"""Remote-job boards with public APIs or RSS feeds."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from pipeline.fetchers import parse_epoch_ms, parse_iso, strip_html
from pipeline.models import Job
from pipeline.sources import session


def remotive(params, terms):
    data = session().get("https://remotive.com/api/remote-jobs", timeout=30).json()
    return [
        Job(
            company=j.get("company_name", ""), title=j.get("title", ""), url=j.get("url", ""),
            source="remotive", location=j.get("candidate_required_location") or "Remote",
            remote=True, posted_at=parse_iso(j.get("publication_date")),
            description=strip_html(j.get("description", "")), employment_type=j.get("job_type", ""),
        )
        for j in data.get("jobs", [])
    ]


def remoteok(params, terms):
    data = session().get("https://remoteok.com/api", timeout=30).json()
    return [
        Job(
            company=j.get("company", ""), title=j.get("position", ""), url=j.get("url", ""),
            source="remoteok", location=j.get("location") or "Remote", remote=True,
            posted_at=parse_iso(j.get("date")), description=strip_html(j.get("description", "")),
        )
        for j in data[1:]  # first element is the API legal notice
        if isinstance(j, dict) and j.get("position")
    ]


def himalayas(params, terms):
    s, jobs, seen = session(), [], set()
    for term in terms:
        data = s.get("https://himalayas.app/jobs/api/search", params={"q": term}, timeout=30).json()
        for j in data.get("jobs", []):
            if j.get("guid") in seen:
                continue
            seen.add(j.get("guid"))
            regions = j.get("locationRestrictions") or []
            jobs.append(Job(
                company=j.get("companyName", ""), title=j.get("title", ""),
                url=j.get("applicationLink") or j.get("guid", ""), source="himalayas",
                location=" / ".join(regions) if regions else "Remote, Worldwide", remote=True,
                posted_at=parse_epoch_ms(int(j["pubDate"]) * 1000) if j.get("pubDate") else None,
                description=strip_html(j.get("description", "")),
                employment_type=j.get("employmentType", ""),
            ))
    return jobs


def jobicy(params, terms):
    s, jobs, seen = session(), [], set()
    for tag in params.get("tags", []):
        data = s.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 100, "tag": tag}, timeout=30).json()
        for j in data.get("jobs", []):
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            jobs.append(Job(
                company=j.get("companyName", ""), title=j.get("jobTitle", ""), url=j.get("url", ""),
                source="jobicy", location=j.get("jobGeo") or "Remote", remote=True,
                posted_at=parse_iso(j.get("pubDate")),
                description=strip_html(j.get("jobDescription", "")),
                employment_type=", ".join(j.get("jobType") or []),
            ))
    return jobs


def weworkremotely(params, terms):
    s, jobs = session(), []
    for feed in params.get("feeds", []):
        r = s.get(f"https://weworkremotely.com/categories/{feed}.rss", timeout=30, allow_redirects=False)
        if r.status_code != 200 or not r.content:
            continue  # renamed/retired category
        root = ET.fromstring(r.content)
        for item in root.iter("item"):
            raw_title = item.findtext("title", "")
            company, _, title = raw_title.partition(": ")
            pub = item.findtext("pubDate")
            jobs.append(Job(
                company=company, title=title or raw_title, url=item.findtext("link", ""),
                source="weworkremotely", location=item.findtext("region") or "Remote", remote=True,
                posted_at=parsedate_to_datetime(pub) if pub else None,
                description=strip_html(item.findtext("description", "")),
                employment_type=item.findtext("type", ""),
            ))
    return jobs


def workingnomads(params, terms):
    data = session().get("https://www.workingnomads.com/api/exposed_jobs/", timeout=30).json()
    return [
        Job(
            company=j.get("company_name", ""), title=j.get("title", ""), url=j.get("url", ""),
            source="workingnomads", location=j.get("location") or "Remote", remote=True,
            posted_at=parse_iso(j.get("pub_date")), description=strip_html(j.get("description", "")),
        )
        for j in data
    ]


MUSE_API = "https://www.themuse.com/api/public/jobs"
MUSE_CATEGORY = "Product Management"
MUSE_LOCATIONS = ["Flexible / Remote", "Bangalore, India"]


def _muse_job(j: dict) -> Job:
    """Map one The Muse API posting to a Job."""
    names = [l.get("name", "") for l in j.get("locations") or [] if l.get("name")]
    return Job(
        company=(j.get("company") or {}).get("name", ""), title=j.get("name", ""),
        url=(j.get("refs") or {}).get("landing_page", ""), source="themuse",
        location=" / ".join(names), remote="Flexible / Remote" in names,
        posted_at=parse_iso(j.get("publication_date")),
        description=strip_html(j.get("contents", "") or ""),
    )


def themuse(params, terms):
    s, jobs, seen = session(), [], set()
    for location in params.get("locations", MUSE_LOCATIONS):
        page, page_count = 0, 1
        while page < page_count and page < 20:
            data = s.get(MUSE_API, params={"category": params.get("category", MUSE_CATEGORY),
                                           "location": location, "page": page}, timeout=30).json()
            page_count = data.get("page_count", 1)
            for j in data.get("results", []):
                if j.get("id") in seen:
                    continue
                seen.add(j.get("id"))
                jobs.append(_muse_job(j))
            page += 1
    return jobs


def jobgether(params, terms):
    """Remote-worldwide product roles with a 1-5 year experience filter."""
    s, jobs, seen = session(), [], set()
    for term in params.get("terms") or terms[:6]:
        data = s.get("https://jobgether.com/api/v1/jobs", timeout=30, params={
            "keyword": term, "locations": "anywhere", "limit": 25,
            "experience": "entry-level-graduate,junior-1-2-years,mid-level-2-5-years"}).json()
        for j in data.get("jobs", []):
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            jobs.append(Job(
                company=j.get("company", ""), title=j.get("title", ""), url=j.get("url", ""),
                source="jobgether", location=j.get("location") or "Anywhere", remote=True,
                posted_at=parse_iso(j.get("postedAt")), description=j.get("experience", ""),
                employment_type=j.get("contractType", ""),
            ))
    return jobs


def arbeitnow(params, terms):
    """Europe (DACH/NL/FR) board; visa or relocation is only visible in the description text."""
    data = session().get("https://www.arbeitnow.com/api/job-board-api", timeout=30).json()
    return [
        Job(
            company=j.get("company_name", ""), title=j.get("title", ""), url=j.get("url", ""),
            source="arbeitnow", location=j.get("location") or "Europe", remote=bool(j.get("remote")),
            posted_at=parse_epoch_ms(int(j["created_at"]) * 1000) if j.get("created_at") else None,
            description=strip_html(j.get("description", "")),
        )
        for j in data.get("data", [])
        if "product" in (j.get("title", "") + " ".join(j.get("tags", []))).lower()
    ]
