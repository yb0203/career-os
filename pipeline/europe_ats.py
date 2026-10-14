"""ATS board fetchers for the Europe search.

Greenhouse, Lever and Ashby reuse the existing `pipeline.fetchers`. This module adds the ATSes
that European employers favour: Workable, SmartRecruiters, Personio, Teamtailor and Recruitee.
All are the public, unauthenticated career-page feeds each ATS publishes for its customers.

Every fetcher is `fetch(company, slug, want=None) -> list[Job]`. `want(job)` lets a fetcher skip
the expensive per-posting description request for roles the caller will drop anyway.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import requests

from pipeline import fetchers as f
from pipeline.models import Job

Want = Optional[Callable[[Job], bool]]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _get(url: str, **kw) -> requests.Response:
    """GET with a polite retry when the ATS answers 429 (Workable does after a handful of calls)."""
    for attempt in range(4):
        resp = requests.get(url, headers=f.HEADERS, timeout=f.TIMEOUT, **kw)
        if resp.status_code != 429 or attempt == 3:
            break
        time.sleep(2 + 3 * attempt)
    resp.raise_for_status()
    return resp


def _json(url: str):
    return _get(url).json()


# ---------------------------------------------------------------- Workable
def workable(company: str, slug: str, want: Want = None) -> list[Job]:
    data = _json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true") or {}
    jobs = []
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        jobs.append(Job(
            company=company, title=j.get("title", ""),
            url=j.get("url") or j.get("shortlink") or "", source="workable", apply_via="workable",
            location=loc, remote=True if j.get("telecommuting") else None,
            posted_at=f.parse_iso(j.get("published_on") or j.get("created_at")),
            description=f.strip_html(j.get("description", "")),
            employment_type=j.get("employment_type", ""),
        ))
    return jobs


# ---------------------------------------------------------------- SmartRecruiters
SR_LIST = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}"
SR_ONE = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}"


def smartrecruiters(company: str, slug: str, want: Want = None) -> list[Job]:
    jobs, offset = [], 0
    while offset < 500:
        data = _json(SR_LIST.format(slug=slug, offset=offset)) or {}
        batch = data.get("content", [])
        for j in batch:
            loc = j.get("location") or {}
            place = ", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x)
            job = Job(
                company=company, title=j.get("name", ""),
                url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", source="smartrecruiters",
                apply_via="smartrecruiters", location=place,
                remote=True if loc.get("remote") else None, posted_at=f.parse_iso(j.get("releasedDate")),
                employment_type=(j.get("typeOfEmployment") or {}).get("label", ""),
            )
            job._sr_id = j.get("id")  # type: ignore[attr-defined]
            jobs.append(job)
        offset += len(batch)
        if not batch or offset >= data.get("totalFound", 0):
            break
    for job in jobs:  # descriptions cost one request each: only for roles the caller wants
        if want and want(job):
            try:
                one = _json(SR_ONE.format(slug=slug, id=job._sr_id)) or {}  # type: ignore[attr-defined]
            except requests.RequestException:
                continue
            sections = ((one.get("jobAd") or {}).get("sections") or {})
            job.description = f.strip_html(" ".join((s or {}).get("text", "") for s in sections.values()))
            job.url = one.get("postingUrl") or job.url
    return jobs


# ---------------------------------------------------------------- Personio
def personio(company: str, slug: str, want: Want = None) -> list[Job]:
    last = None
    for tld in ("de", "com"):
        try:
            resp = _get(f"https://{slug}.jobs.personio.{tld}/xml?language=en")
            break
        except requests.RequestException as exc:
            last = exc
    else:
        raise last  # type: ignore[misc]
    root = ET.fromstring(resp.content)
    host = resp.url.split("/xml")[0]
    jobs = []
    for pos in root.iter("position"):
        get = lambda tag: (pos.findtext(tag) or "").strip()
        offices = [get("office")] + [(o.text or "").strip() for o in pos.findall("additionalOffices/office")]
        desc = " ".join(
            f"{jd.findtext('name') or ''} {f.strip_html(jd.findtext('value') or '')}"
            for jd in pos.iter("jobDescription")
        )
        jobs.append(Job(
            company=company, title=get("name"), url=f"{host}/job/{get('id')}", source="personio",
            apply_via="personio", location=" / ".join(o for o in offices if o),
            remote=True if re.search(r"\bremote\b", " ".join(offices), re.I) else None,
            posted_at=f.parse_iso(get("createdAt")), description=desc,
            employment_type=get("employmentType") or get("schedule"),
        ))
    return jobs


# ---------------------------------------------------------------- Teamtailor
def teamtailor(company: str, slug: str, want: Want = None) -> list[Job]:
    resp = _get(f"https://{slug}.teamtailor.com/jobs.rss")
    root = ET.fromstring(resp.content)
    jobs = []
    for item in root.iter("item"):
        fields = {_local(c.tag): (c.text or "").strip() for c in item}
        places = []
        for loc in item.iter():
            if _local(loc.tag) == "location":
                parts = {_local(c.tag): (c.text or "").strip() for c in loc}
                place = ", ".join(x for x in (parts.get("city"), parts.get("country")) if x)
                if place:
                    places.append(place)
        status = fields.get("remoteStatus", "").lower()
        pub = fields.get("pubDate")
        try:
            posted = parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            posted = None
        jobs.append(Job(
            company=company, title=fields.get("title", ""), url=fields.get("link", ""),
            source="teamtailor", apply_via="teamtailor", location=" / ".join(dict.fromkeys(places)),
            remote=True if status in ("fully", "remote", "full") else None, posted_at=posted,
            description=f.strip_html(fields.get("description", "")),
        ))
    return jobs


# ---------------------------------------------------------------- Recruitee
def recruitee(company: str, slug: str, want: Want = None) -> list[Job]:
    data = _json(f"https://{slug}.recruitee.com/api/offers/") or {}
    jobs = []
    for j in data.get("offers", []):
        if j.get("status") not in (None, "published"):
            continue
        loc = j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        jobs.append(Job(
            company=company, title=j.get("title", ""), url=j.get("careers_url", ""), source="recruitee",
            apply_via="recruitee", location=loc, remote=True if j.get("remote") else None,
            posted_at=f.parse_iso(j.get("published_at") or j.get("created_at")),
            description=f.strip_html((j.get("description") or "") + " " + (j.get("requirements") or "")),
            employment_type=j.get("employment_type_code", ""),
        ))
    return jobs


def _wrap(fetch: Callable[[str, str], list[Job]]) -> Callable[..., list[Job]]:
    def inner(company: str, slug: str, want: Want = None) -> list[Job]:
        return fetch(company, slug)
    return inner


ATS_FETCHERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": _wrap(f.FETCHERS["greenhouse"]),
    "lever": _wrap(f.FETCHERS["lever"]),
    "ashby": _wrap(f.FETCHERS["ashby"]),
    "workable": workable,
    "smartrecruiters": smartrecruiters,
    "personio": personio,
    "teamtailor": teamtailor,
    "recruitee": recruitee,
}
