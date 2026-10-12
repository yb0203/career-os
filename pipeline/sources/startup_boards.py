"""Startup and VC-portfolio job boards: YC, Getro-powered and Consider-powered boards."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone

from pipeline.fetchers import parse_iso
from pipeline.models import Job
from pipeline.sources import next_data, session


def yc(params, terms):
    s, jobs, seen = session(), [], set()
    for page in params.get("pages", []):
        text = s.get(f"https://www.ycombinator.com/jobs/{page}", timeout=30).text
        m = re.search(r'data-page="([^"]+)"', text)
        if not m:
            continue
        for j in json.loads(html.unescape(m.group(1)))["props"].get("jobPostings", []):
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            loc = j.get("location", "")
            jobs.append(Job(
                company=j.get("companyName", ""), title=j.get("title", ""),
                url="https://www.ycombinator.com" + j.get("url", ""), source="yc", location=loc,
                remote="remote" in loc.lower() or None, employment_type=j.get("type", ""),
                description=f"{j.get('minExperience', '')} experience. {j.get('companyOneLiner', '')}",
            ))
    return jobs


def getro(params, terms):
    s, jobs, seen = session(), [], set()
    for host in params.get("boards", []):
        try:
            network = next_data(s.get(f"https://{host}/jobs", timeout=30).text)["props"]["pageProps"]["network"]
        except (KeyError, TypeError, ValueError):
            continue
        headers = {"Accept": "application/json", "Origin": f"https://{host}", "Referer": f"https://{host}/"}
        for term in terms:
            r = s.post(f"https://api.getro.com/api/v2/collections/{network['id']}/search/jobs",
                       headers=headers, timeout=30,
                       json={"hitsPerPage": 100, "page": 0, "filters": {"page": 0}, "query": term})
            if r.status_code != 200:
                break
            for j in r.json().get("results", {}).get("jobs", []):
                if j["url"] in seen:
                    continue
                seen.add(j["url"])
                locs = j.get("locations") or j.get("searchable_locations") or []
                remote = j.get("work_mode") == "remote"
                jobs.append(Job(
                    company=(j.get("organization") or {}).get("name", ""), title=j.get("title", ""),
                    url=j["url"], source=f"getro:{host}",
                    location=" / ".join(locs) or ("Remote" if remote else ""), remote=remote or None,
                    posted_at=datetime.fromtimestamp(j["created_at"], tz=timezone.utc) if j.get("created_at") else None,
                ))
    return jobs


def consider(params, terms):
    """Consider boards ignore free-text queries, so pull India-located roles and remote roles."""
    jobs, seen = [], set()
    for host, board_id in (params.get("boards") or {}).items():
        s = session()
        page = s.get(f"https://{host}/jobs", timeout=30).text
        tok = re.search(r'csrf[-_]?token["\':= ]+([A-Za-z0-9_\-+/=]{16,})', page, re.I)
        if not tok:
            continue
        headers = {"Accept": "application/json", "Origin": f"https://{host}",
                   "Referer": f"https://{host}/jobs", "x-csrf-token": tok.group(1)}
        for query in ({"locations": ["India"]}, {"remoteOnly": True}):
            r = s.post(f"https://{host}/api-boards/search-jobs", headers=headers, timeout=30,
                       json={"meta": {"size": 500}, "board": {"id": board_id, "isParent": True}, "query": query})
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs", []):
                url = j.get("applyUrl") or j.get("url", "")
                if url in seen or (j.get("applicationWindow") or {}).get("status") not in (None, "accepting"):
                    continue
                seen.add(url)
                jobs.append(Job(
                    company=j.get("companyName", ""), title=j.get("title", ""), url=url,
                    source=f"consider:{host}", location=" / ".join(j.get("locations") or []),
                    remote=bool(j.get("remote")) or None, posted_at=parse_iso(j.get("timeStamp")),
                    employment_type="contract" if j.get("contractor") else "",
                ))
    return jobs
