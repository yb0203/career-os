"""Tier-2 sources: job boards, aggregators, communities and VC portfolio boards.

Each source is `fetch(params: dict, terms: list[str]) -> list[Job]`.
"""
from __future__ import annotations

import json
import re
from typing import Callable

import requests

from pipeline.models import Job

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129 Safari/537.36"
)


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = BROWSER_UA
    return s


def next_data(html_text: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.S)
    return json.loads(m.group(1)) if m else {}


def find_list(obj, key: str):
    """First non-empty list stored under `key` anywhere in a nested JSON blob."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, list) and v:
                return v
            found = find_list(v, key)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_list(v, key)
            if found:
                return found
    return None


from pipeline.sources import community, india, remote_boards, startup_boards  # noqa: E402

SOURCES: dict[str, Callable[[dict, list], list[Job]]] = {
    "remotive": remote_boards.remotive,
    "remoteok": remote_boards.remoteok,
    "himalayas": remote_boards.himalayas,
    "jobicy": remote_boards.jobicy,
    "weworkremotely": remote_boards.weworkremotely,
    "workingnomads": remote_boards.workingnomads,
    "themuse": remote_boards.themuse,
    "hn_whoishiring": community.hn_whoishiring,
    "linkedin": india.linkedin,
    "instahyre": india.instahyre,
    "cutshort": india.cutshort,
    "yc": startup_boards.yc,
    "getro": startup_boards.getro,
    "consider": startup_boards.consider,
}
