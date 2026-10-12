"""Normalized job record shared by every fetcher, gate and scorer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Job:
    company: str
    title: str
    url: str
    source: str  # greenhouse | lever | ashby
    location: str = ""
    remote: Optional[bool] = None
    posted_at: Optional[datetime] = None
    description: str = ""
    employment_type: str = ""
    # Filled in by gates/scorer
    lane: str = ""
    score: int = 0
    priority: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def age_days(self) -> Optional[float]:
        if self.posted_at is None:
            return None
        return (datetime.now(timezone.utc) - self.posted_at).total_seconds() / 86400

    def to_row(self) -> dict:
        row = asdict(self)
        row.pop("description")
        row["posted_at"] = self.posted_at.date().isoformat() if self.posted_at else ""
        row["reasons"] = "; ".join(self.reasons)
        return row
