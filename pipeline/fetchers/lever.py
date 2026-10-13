from __future__ import annotations

from pipeline import fetchers as f
from pipeline.models import Job

URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


def fetch(company: str, slug: str) -> list[Job]:
    jobs = []
    for j in f.get_json(URL.format(slug=slug)):
        cats = j.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location", "")]
        workplace = (j.get("workplaceType") or "").lower()
        jobs.append(
            Job(
                company=company,
                title=j.get("text", ""),
                url=j.get("hostedUrl", ""),
                source="lever",
                apply_via="lever",
                location=" / ".join(filter(None, locations)),
                remote=True if workplace == "remote" else (False if workplace else None),
                posted_at=f.parse_epoch_ms(j.get("createdAt")),
                description=j.get("descriptionPlain", "") + " " + j.get("additionalPlain", ""),
                employment_type=cats.get("commitment", ""),
            )
        )
    return jobs
