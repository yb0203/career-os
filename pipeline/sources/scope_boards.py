"""Scope-driven boards: fresher/internship, India startup and remote-global boards.

Added 2026-10-14. Everything here is read without a login and without JavaScript:
Unstop (public JSON API), Internshala (server-rendered cards), Wellfound (server-rendered
Apollo state on public role pages), Weekday (sitemaps + JobPosting JSON-LD), Remote Rocketship
(server-rendered Next.js data) and Hasjob (Atom feed). Each has a pure mapping helper so tests
need no network. Requests are few and spaced out; any non-200 or bot check just ends that board.
"""
from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

from pipeline.fetchers import parse_iso, strip_html
from pipeline.models import Job
from pipeline.sources import next_data, session

PAUSE = 0.4  # seconds between requests to the same site


def _sleep(seconds: float = PAUSE) -> None:
    time.sleep(seconds)


# --------------------------------------------------------------------------- Unstop

UNSTOP_API = "https://unstop.com/api/public/opportunity/search-result"
UNSTOP_TERMS = ["product manager", "product", "founder's office", "chief of staff", "growth",
                "business operations", "strategy", "program manager"]


def _parse_unstop_date(value: str) -> Optional[datetime]:
    """'2026-10-10 19:55:49 GMT+0530' or '2026-10-12T22:22:56+05:30' -> aware datetime."""
    if not value:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s*(?:GMT)?([+-]\d{2}):?(\d{2})?$", value.strip())
    if not m:
        return parse_iso(value)
    return parse_iso(f"{m.group(1)}T{m.group(2)}{m.group(3)}:{m.group(4) or '00'}")


def _unstop_job(j: dict) -> Job:
    """Map one Unstop opportunity (job or internship) to a Job."""
    detail = j.get("jobDetail") or {}
    cities = [l.get("city") for l in j.get("locations") or [] if l.get("city")]
    cities = cities or [c for c in detail.get("locations") or [] if c]
    wfh = detail.get("type") == "wfh"
    # City names only: tagging every row "India" would let Mumbai/Pune roles through the location gate
    location = ", ".join(dict.fromkeys(cities))
    if wfh:
        location = "Remote, India"
    internship = j.get("subtype") == "internships"
    pay = ""
    if detail.get("show_salary") and (detail.get("min_salary") or detail.get("max_salary")):
        lo, hi = detail.get("min_salary"), detail.get("max_salary")
        pay = f"Pay: Rs {lo}-{hi} {detail.get('pay_in', '')}. "
    elig = [f.get("name", "") for f in j.get("filters") or [] if f.get("type") == "eligible"]
    prefix = f"{pay}Open to: {', '.join(elig)}. " if elig else pay
    return Job(
        company=(j.get("organisation") or {}).get("name", ""), title=(j.get("title") or "").strip(),
        url=j.get("seo_url") or f"https://unstop.com/{j.get('public_url', '')}", source="unstop",
        location=location, remote=True if wfh else None,
        posted_at=_parse_unstop_date(j.get("approved_date") or j.get("updated_at") or ""),
        description=prefix + strip_html(j.get("details", "")),
        employment_type="internship" if internship else (detail.get("timing") or "").replace("_", "-"),
    )


def _unstop_unpaid(j: dict) -> bool:
    return (j.get("jobDetail") or {}).get("paid_unpaid") == "unpaid"


def unstop(params, terms):
    s, jobs, seen = session(), [], set()
    for kind in params.get("opportunities", ["jobs", "internships"]):
        for term in params.get("terms", UNSTOP_TERMS):
            r = s.get(UNSTOP_API, timeout=30, params={
                "opportunity": kind, "per_page": 50, "oppstatus": "open", "searchTerm": term})
            _sleep()
            if r.status_code != 200:
                continue
            for j in r.json().get("data", {}).get("data", []):
                if j.get("id") in seen or j.get("status") != "LIVE":
                    continue
                if _unstop_unpaid(j) and not params.get("include_unpaid"):
                    continue  # scope is paid internships only
                seen.add(j.get("id"))
                jobs.append(_unstop_job(j))
    return jobs


# --------------------------------------------------------------------------- Internshala

INTERNSHALA = "https://internshala.com"
INTERNSHALA_PAGES = [
    "internships/product-management-internship/",
    "internships/product-management-internship-in-bangalore/",
    "internships/work-from-home-product-management-internships/",
    "internships/operations-internship/",
    "internships/strategy-internship/",
    "internships/business-development-internship/",
    "jobs/product-manager-jobs/",
    "jobs/product-manager-jobs-in-bangalore/",
    "jobs/program-manager-jobs/",
    "jobs/founders-office-jobs/",
    "jobs/strategy-jobs/",
    "jobs/business-development-jobs-in-bangalore/",
    "fresher-jobs/product-manager-jobs/",
]
_CARD_SPLIT = re.compile(r'(?=<div class="container-fluid individual_internship)')
_AGO = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s+ago", re.I)


def _ago(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """'3 weeks ago' / 'Just now' / 'Today' -> approximate datetime."""
    now = now or datetime.now(timezone.utc)
    t = (text or "").strip().lower()
    if t in ("just now", "today"):
        return now
    m = _AGO.search(t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return now - timedelta(**{unit + "s" if unit != "month" else "days": n * (30 if unit == "month" else 1)})


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", strip_html(fragment)).strip()


def _internshala_cards(page_html: str, now: Optional[datetime] = None, include_unpaid: bool = False) -> list[Job]:
    """Map the server-rendered result cards on an Internshala listing page (paid roles only by default)."""
    jobs = []
    for card in _CARD_SPLIT.split(page_html):
        if not card.startswith('<div class="container-fluid individual_internship'):
            continue
        href = re.search(r"data-href=['\"]([^'\"]+)", card)
        title = re.search(r'class="job-title-href"[^>]*>(.*?)</a>', card, re.S)
        company = re.search(r'class="company-name">(.*?)</p>', card, re.S)
        if not (href and title and company):
            continue
        kind = re.search(r'employment_type="(\w+)"', card)
        loc_block = re.search(r'class="row-1-item locations">(.*?)<!-- /location', card, re.S)
        location = _clean(loc_block.group(1)) if loc_block else ""
        remote = "work from home" in location.lower()
        money = re.search(r'class=[\'"]stipend[\'"]>(.*?)</span>', card, re.S) or \
            re.search(r'<span class="desktop">(.*?)</span>', card, re.S)
        if money and "unpaid" in money.group(1).lower() and not include_unpaid:
            continue
        exp = re.search(r'ic-16-briefcase"></i>\s*<span>(.*?)</span>', card, re.S)
        about = re.search(r'<div class="text">(.*?)</div>', card, re.S)
        ago = re.search(r'ic-16-reschedule"></i><span>(.*?)</span>', card, re.S)
        extras = []
        if money:
            extras.append("Pay: " + _clean(money.group(1)))
        if exp:
            extras.append(_clean(exp.group(1)))
        if re.search(r"fresher", card, re.I):
            extras.append("Fresher friendly")
        jobs.append(Job(
            company=_clean(company.group(1)), title=_clean(title.group(1)),
            url=INTERNSHALA + href.group(1), source="internshala",
            location="Remote, India" if remote else location,
            remote=True if remote else None, posted_at=_ago(_clean(ago.group(1)), now) if ago else None,
            description=". ".join(extras + ([_clean(about.group(1))] if about else [])),
            employment_type="internship" if kind and kind.group(1) == "internship" else "",
        ))
    return jobs


def internshala(params, terms):
    s, jobs, seen = session(), [], set()
    for page in params.get("pages", INTERNSHALA_PAGES):
        r = s.get(f"{INTERNSHALA}/{page}", timeout=30)
        _sleep(1.0)
        # an unknown slug redirects to the generic /jobs/ or /internships/ index: skip it
        if r.status_code != 200 or urlparse_path(r.url) in ("/jobs/", "/internships/", "/jobs", "/internships"):
            continue
        for j in _internshala_cards(r.text, include_unpaid=bool(params.get('include_unpaid'))):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    return jobs


def urlparse_path(url: str) -> str:
    return re.sub(r"^https?://[^/]+", "", url).split("?")[0]


# --------------------------------------------------------------------------- Wellfound

WELLFOUND = "https://wellfound.com"
WELLFOUND_ROLES = ["product-manager", "associate-product-manager", "product-owner", "program-manager",
                   "technical-program-manager", "chief-of-staff", "founders-office", "growth-manager",
                   "business-operations-manager", "strategy-manager", "operations-manager",
                   "business-development-manager"]
_NCR_ROLES = ["product-manager", "associate-product-manager", "chief-of-staff", "founders-office",
              "growth-manager", "program-manager"]
WELLFOUND_SEARCHES = [{"location": "india", "roles": WELLFOUND_ROLES}] + [
    {"location": city, "roles": _NCR_ROLES} for city in ("gurgaon", "new-delhi", "noida")]
_REMOTE_KINDS = {"REMOTE", "REMOTE_ONLY", "FULLY_REMOTE"}


def _wellfound_jobs(apollo: dict) -> list[Job]:
    """Map the Apollo cache of a Wellfound role page (location names are real cities)."""
    owner = {}
    for key, val in apollo.items():
        if key.startswith("StartupResult"):
            for ref in val.get("highlightedJobListings") or []:
                owner[ref.get("__ref")] = val
    jobs = []
    for key, j in apollo.items():
        if not key.startswith("JobListingSearchResult") or key not in owner:
            continue
        cfg = j.get("remoteConfig") or {}
        remote = bool(j.get("remote")) or cfg.get("kind") in _REMOTE_KINDS
        names = list(j.get("locationNames") or []) + list(j.get("acceptedRemoteLocationNames") or [])
        location = ", ".join(dict.fromkeys(names))
        if remote:
            location = f"Remote, {location}" if location else "Remote"
        extras = []
        if j.get("compensation"):
            extras.append("Pay: " + j["compensation"])
        if j.get("yearsExperienceMin") is not None:
            extras.append(f"{j['yearsExperienceMin']}+ years experience")
        live = j.get("liveStartAt")
        jobs.append(Job(
            company=owner[key].get("name", ""), title=(j.get("title") or "").strip(),
            url=f"{WELLFOUND}/jobs/{j.get('id')}-{j.get('slug', '')}", source="wellfound",
            location=location, remote=True if remote else None,
            posted_at=datetime.fromtimestamp(live, tz=timezone.utc) if live else None,
            description=". ".join(extras + [html.unescape(j.get("description") or "")]),
            employment_type=(j.get("jobType") or ""),
        ))
    return jobs


def wellfound(params, terms):
    """`searches`: list of {location, roles}; defaults cover India-wide plus the NCR cities."""
    s, jobs, seen = session(), [], set()
    searches = params.get("searches") or WELLFOUND_SEARCHES
    for search in searches:
        for role in search["roles"]:
            r = s.get(f"{WELLFOUND}/role/l/{role}/{search['location']}", timeout=30)
            _sleep(1.0)
            if r.status_code != 200:
                break  # blocked or renamed: stop quietly
            try:
                apollo = next_data(r.text)["props"]["pageProps"]["apolloState"]["data"]
            except (KeyError, TypeError, ValueError):
                break
            for j in _wellfound_jobs(apollo):
                if j.url not in seen:
                    seen.add(j.url)
                    jobs.append(j)
    return jobs


# --------------------------------------------------------------------------- Weekday

WEEKDAY = "https://jobs.weekday.works"
WEEKDAY_SITEMAPS = ["product_management-0", "program_project_management-0",
                    "general_management_exec-0", "operations_strategy-0"]
_WEEKDAY_SLUG = re.compile(
    r"product-(manager|owner|lead|operations|analyst|management)|associate-product|program-manager|"
    r"chief-of-staff|founder|growth|strategy|business-operations|bizops|solutions-(engineer|consultant)|"
    r"implementation|operations-manager|business-analyst|gtm|go-to-market|revenue-operations|"
    r"fractional|contract|intern(ship)?-|-intern-", re.I)


def _weekday_candidates(sitemap_xml: str, now: datetime, max_age_days: int) -> list[tuple[str, datetime]]:
    """(url, lastmod) pairs that are recent and whose slug looks like a target title, newest first."""
    out = []
    for loc, mod in re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", sitemap_xml):
        when = parse_iso(mod)
        if when and now - when <= timedelta(days=max_age_days) and _WEEKDAY_SLUG.search(loc.rsplit("/", 1)[-1]):
            out.append((loc, when))
    return sorted(out, key=lambda x: x[1], reverse=True)


def _weekday_job(ld: dict, url: str) -> Job:
    """Map a Weekday JobPosting JSON-LD block to a Job."""
    places = ld.get("jobLocation") or []
    places = [places] if isinstance(places, dict) else places
    parts = []
    for p in places:
        addr = p.get("address") or {}
        country = addr.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        if addr.get("addressLocality"):  # a named city: drop the country so "India" can't mask Mumbai/Pune
            parts += [addr.get("addressLocality"), addr.get("addressRegion")]
        else:
            parts += [addr.get("addressRegion"), country]
    pieces = [x.strip() for x in ", ".join(x for x in parts if isinstance(x, str) and x).split(",") if x.strip()]
    pieces = list(dict.fromkeys(pieces))
    if len(pieces) > 1 and pieces[-1].lower() == "india":
        pieces.pop()  # "Mumbai, Maharashtra, India" -> keep the city, or "India" would mask excluded cities
    location = ", ".join(pieces)
    remote = "TELECOMMUTE" in str(ld.get("jobLocationType", "")).upper() or "remote" in location.lower()
    return Job(
        company=(ld.get("hiringOrganization") or {}).get("name", ""), title=(ld.get("title") or "").strip(),
        url=url, source="weekday", location=location, remote=True if remote else None,
        posted_at=parse_iso(ld.get("datePosted")), description=strip_html(ld.get("description", "")),
        employment_type=(ld.get("employmentType") or "").lower().replace("_", "-")
        if isinstance(ld.get("employmentType"), str) else "",
    )


def _job_posting(page_html: str) -> Optional[dict]:
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def weekday(params, terms):
    s, jobs = session(), []
    now = datetime.now(timezone.utc)
    cands = []
    for name in params.get("sitemaps", WEEKDAY_SITEMAPS):
        r = s.get(f"{WEEKDAY}/sitemaps/jobs/{name}.xml", timeout=30)
        _sleep()
        if r.status_code == 200:
            cands += _weekday_candidates(r.text, now, params.get("max_age_days", 14))
    cands.sort(key=lambda x: x[1], reverse=True)
    for url, _ in cands[: params.get("max_pages", 150)]:
        r = s.get(url, timeout=30)
        _sleep(0.3)
        ld = _job_posting(r.text) if r.status_code == 200 else None
        if ld:
            jobs.append(_weekday_job(ld, url))
    return jobs


# --------------------------------------------------------------------------- Remote Rocketship

ROCKETSHIP = "https://remoterocketship.com"
ROCKETSHIP_INDIA = ["product-manager", "growth-manager", "chief-of-staff", "program-manager",
                    "technical-program-manager", "product-owner", "business-analyst", "product-analyst",
                    "implementation-manager", "solutions-engineer"]
ROCKETSHIP_GLOBAL = ["product-manager", "growth-manager", "chief-of-staff", "technical-program-manager"]


def _rocketship_job(j: dict) -> Job:
    """Map one Remote Rocketship opening (url is the company's own ATS posting)."""
    flags = [name for key, name in (("isEntryLevel", "entry level"), ("isJunior", "junior"),
                                    ("isMidLevel", "mid level"), ("isSenior", "senior")) if j.get(key)]
    summary = j.get("jobDescriptionSummary") or j.get("twoLineJobDescriptionSummary") or ""
    return Job(
        company=(j.get("company") or {}).get("name", ""), title=(j.get("roleTitle") or "").strip(),
        url=j.get("url", ""), source="remoterocketship", location=j.get("location") or "",
        remote=True if j.get("locationType") == "remote" else None, posted_at=parse_iso(j.get("created_at")),
        description=(f"Level: {', '.join(flags)}. " if flags else "") + summary,
        employment_type=(j.get("employmentType") or "").replace("_", "-"),
    )


def remoterocketship(params, terms):
    s, jobs, seen = session(), [], set()
    pages = [(f"{ROCKETSHIP}/country/india/jobs/{slug}", None) for slug in params.get("india", ROCKETSHIP_INDIA)]
    for slug in params.get("worldwide", ROCKETSHIP_GLOBAL):
        for page in range(1, params.get("worldwide_pages", 2) + 1):
            pages.append((f"{ROCKETSHIP}/jobs/{slug}", page))
    for url, page in pages:
        r = s.get(url, timeout=30, params={"page": page} if page and page > 1 else None)
        _sleep(1.0)
        if r.status_code != 200:
            continue
        try:
            openings = next_data(r.text)["props"]["pageProps"].get("initialJobOpenings") or []
        except (KeyError, TypeError, ValueError):
            continue
        for j in openings:
            if j.get("id") not in seen and not j.get("dateDeleted"):
                seen.add(j.get("id"))
                jobs.append(_rocketship_job(j))
    return jobs


# --------------------------------------------------------------------------- Hasjob

def _hasjob_entries(feed_xml: str) -> list[Job]:
    """Map Hasjob Atom entries. The first <strong> in the HTML body is the company name."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(feed_xml.encode() if isinstance(feed_xml, str) else feed_xml)
    jobs = []
    for e in root.findall("a:entry", ns):
        body = e.findtext("a:content", "", ns) or ""
        company = re.search(r"<strong>(.*?)</strong>", body, re.S)
        link = e.find("a:link", ns)
        location = e.findtext("a:location", "", ns) or e.findtext("location", "") or ""
        jobs.append(Job(
            company=_clean(company.group(1)) if company else "", title=(e.findtext("a:title", "", ns) or "").strip(),
            url=link.get("href", "") if link is not None else "", source="hasjob", location=location,
            remote=True if "anywhere" in location.lower() or "remote" in location.lower() else None,
            posted_at=parse_iso(e.findtext("a:published", "", ns)), description=strip_html(body),
        ))
    return jobs


def hasjob(params, terms):
    r = session().get("https://hasjob.co/feed", timeout=30)
    return _hasjob_entries(r.content) if r.status_code == 200 else []
