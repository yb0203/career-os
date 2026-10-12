"""Find which ATS a company uses:  python -m pipeline.probe razorpay groww cred"""
from __future__ import annotations

import sys

from pipeline.fetchers import FETCHERS


def probe(slug: str) -> list[tuple[str, int]]:
    found = []
    for ats, fetch in FETCHERS.items():
        try:
            jobs = fetch(slug, slug)
        except Exception:
            continue
        if jobs:
            found.append((ats, len(jobs)))
    return found


if __name__ == "__main__":
    for s in sys.argv[1:]:
        hits = probe(s)
        print(s, ", ".join(f"{a} ({n} jobs)" for a, n in hits) or "no public board found")
