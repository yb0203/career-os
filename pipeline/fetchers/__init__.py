"""Tier-1 fetchers: public job-board APIs straight from each company's ATS.

Postings come from the origin, so they are live by definition (no dead aggregator reposts).
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Callable, Optional

import requests

from pipeline.models import Job

TIMEOUT = 20
HEADERS = {"User-Agent": "career-os/0.1 (+https://github.com/yb0203/career-os)"}


def get_json(url: str, retries: int = 2):
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == retries:
                raise


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_epoch_ms(value) -> Optional[datetime]:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc) if value else None


from pipeline.fetchers import ashby, greenhouse, lever  # noqa: E402

FETCHERS: dict[str, Callable[[str, str], list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}
