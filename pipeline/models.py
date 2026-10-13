"""Normalized job record shared by every fetcher, gate and scorer."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

# Hostnames whose second-level label isn't the name people know the platform by
_HOST_ALIASES = {"ashbyhq": "ashby", "myworkdayjobs": "workday"}


def apply_via(url: str, fallback: str = "") -> str:
    """Where you actually apply, from the posting URL: 'https://jobs.lever.co/x' -> 'lever'."""
    host = (urlparse(url or "").hostname or "").lower()
    labels = [x for x in host.split(".") if x and x != "www"]
    if len(labels) < 2:
        return fallback
    # co.in / com.au style suffixes: the name sits one label further left
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("co", "com", "org", "net", "ac"):
        name = labels[-3]
    else:
        name = labels[-2]
    return _HOST_ALIASES.get(name, name)


@dataclass
class Job:
    company: str
    title: str
    url: str
    source: str  # greenhouse | lever | ashby | <source name>
    location: str = ""
    remote: Optional[bool] = None
    posted_at: Optional[datetime] = None
    description: str = ""
    employment_type: str = ""
    # Where the apply button lives: the ATS for watchlist fetchers, else the posting URL's domain
    apply_via: str = ""
    # Filled in by gates/scorer
    lane: str = ""
    score: int = 0
    priority: str = ""
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.apply_via:  # safety net for any source that forgets to set it
            self.apply_via = apply_via(self.url, self.source.split(":")[0])

    @property
    def id(self) -> str:
        """Stable across runs and sources: same company + title -> same ID."""
        key = re.sub(r"[^a-z0-9]", "", self.company.lower()) + "|" + re.sub(r"[^a-z0-9]", "", self.title.lower())
        return hashlib.sha1(key.encode()).hexdigest()[:10]

    @property
    def age_days(self) -> Optional[float]:
        if self.posted_at is None:
            return None
        return (datetime.now(timezone.utc) - self.posted_at).total_seconds() / 86400

    def to_row(self) -> dict:
        row = asdict(self)
        row.pop("description")
        row["id"] = self.id
        row["posted_at"] = self.posted_at.date().isoformat() if self.posted_at else ""
        row["reasons"] = "; ".join(self.reasons)
        return row
