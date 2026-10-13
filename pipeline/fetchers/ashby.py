from __future__ import annotations

from pipeline import fetchers as f
from pipeline.models import Job

URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def fetch(company: str, slug: str) -> list[Job]:
    data = f.get_json(URL.format(slug=slug))
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locations = [j.get("location", "")] + [
            s.get("location", "") for s in j.get("secondaryLocations") or []
        ]
        jobs.append(
            Job(
                company=company,
                title=j.get("title", ""),
                url=j.get("jobUrl", ""),
                source="ashby",
                apply_via="ashby",
                location=" / ".join(filter(None, locations)),
                remote=j.get("isRemote"),
                posted_at=f.parse_iso(j.get("publishedAt")),
                description=j.get("descriptionPlain", ""),
                employment_type=j.get("employmentType", ""),
            )
        )
    return jobs
