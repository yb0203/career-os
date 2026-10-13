from __future__ import annotations

from pipeline import fetchers as f
from pipeline.models import Job

URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def fetch(company: str, slug: str) -> list[Job]:
    data = f.get_json(URL.format(slug=slug))
    jobs = []
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name", "")
        jobs.append(
            Job(
                company=company,
                title=j.get("title", ""),
                url=j.get("absolute_url", ""),
                source="greenhouse",
                apply_via="greenhouse",
                location=location,
                remote="remote" in location.lower() or None,
                # first_published is the original post date; updated_at moves on every edit
                posted_at=f.parse_iso(j.get("first_published") or j.get("updated_at")),
                description=f.strip_html(j.get("content", "")),
            )
        )
    return jobs
