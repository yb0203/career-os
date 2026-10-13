"""Community hiring threads."""
from __future__ import annotations

from pipeline.fetchers import parse_iso, strip_html
from pipeline.models import Job
from pipeline.sources import session

ALGOLIA = "https://hn.algolia.com/api/v1"


def hn_whoishiring(params, terms):
    """Top-level comments of the latest 'Ask HN: Who is hiring?' thread.

    Convention: first line is 'Company | Role | Location | ...'.
    """
    s = session()
    stories = s.get(f"{ALGOLIA}/search_by_date",
                    params={"tags": "story,author_whoishiring", "hitsPerPage": 5}, timeout=30).json()
    thread = next(h for h in stories["hits"] if "who is hiring" in h["title"].lower())
    jobs, page = [], 0
    while True:
        data = s.get(f"{ALGOLIA}/search", timeout=30, params={
            "tags": f"comment,story_{thread['objectID']}", "hitsPerPage": 1000, "page": page}).json()
        for c in data.get("hits", []):
            if str(c.get("parent_id")) != str(thread["objectID"]):
                continue  # replies, not postings
            text = c.get("comment_text") or ""
            first = strip_html(text.split("<p>")[0])
            parts = [p.strip() for p in first.split("|")]
            if len(parts) < 2:
                continue
            location = next((p for p in parts[2:] if any(
                w in p.lower() for w in ("remote", "onsite", "hybrid", "india", "bangalore", ","))), "")
            jobs.append(Job(
                company=parts[0][:80], title=" | ".join(parts[1:3])[:160],
                url=f"https://news.ycombinator.com/item?id={c['objectID']}", source="hn_whoishiring", apply_via="hackernews",
                location=location, remote="remote" in first.lower() or None,
                posted_at=parse_iso(c.get("created_at")), description=strip_html(text),
            ))
        page += 1
        if page >= data.get("nbPages", 0):
            return jobs
