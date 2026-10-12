"""Daily run: fetch watchlist boards -> gates -> score -> output/jobs.csv + output/digest.md

    python -m pipeline.run [--limit N] [--company NAME]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pipeline import gates, scorer
from pipeline.fetchers import FETCHERS
from pipeline.models import Job

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())


def fetch_all(watchlist: list[dict]) -> tuple[list[Job], list[str]]:
    jobs, errors = [], []

    def one(entry):
        return entry, FETCHERS[entry["ats"]](entry["name"], entry["slug"])

    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(one, e) for e in watchlist]
        for fut in cf.as_completed(futures):
            try:
                _, got = fut.result()
                jobs.extend(got)
            except Exception as exc:  # one bad board shouldn't sink the run
                errors.append(str(exc)[:200])
    return jobs, errors


def write_outputs(kept: list[Job], scanned: int, boards: int, errors: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    kept.sort(key=lambda j: (-j.score, j.age_days if j.age_days is not None else 99))
    fields = ["priority", "score", "lane", "company", "title", "location", "posted_at",
              "source", "url", "employment_type", "remote", "reasons"]
    with (OUT / "jobs.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for j in kept:
            w.writerow(j.to_row())

    today = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"# Daily job digest — {today}",
        "",
        f"Scanned **{scanned}** live postings across **{boards}** company boards → "
        f"**{len(kept)}** passed the gates "
        f"({sum(j.priority == 'P0' for j in kept)} P0, {sum(j.priority == 'P1' for j in kept)} P1).",
        "",
        "| Pri | Score | Lane | Company | Role | Location | Posted |",
        "|---|---|---|---|---|---|---|",
    ]
    for j in kept:
        if j.priority == "P2":
            continue
        posted = j.posted_at.date().isoformat() if j.posted_at else "?"
        lines.append(f"| {j.priority} | {j.score} | {j.lane} | {j.company} | "
                     f"[{j.title}]({j.url}) | {j.location} | {posted} |")
    if errors:
        lines += ["", f"<details><summary>{len(errors)} board errors</summary>", ""]
        lines += [f"- {e}" for e in errors]
        lines += ["", "</details>"]
    (OUT / "digest.md").write_text("\n".join(lines) + "\n")


def main(argv=None) -> list[Job]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first N watchlist companies")
    ap.add_argument("--company", help="only this company (name match)")
    args = ap.parse_args(argv)

    cfg = load_yaml("config/lanes.yaml")
    watchlist = load_yaml("watchlist.yaml")["companies"]
    if args.company:
        watchlist = [c for c in watchlist if c["name"].lower() == args.company.lower()]
    if args.limit:
        watchlist = watchlist[: args.limit]

    jobs, errors = fetch_all(watchlist)
    kept = [scorer.score(j, cfg) for j in jobs if gates.apply(j, cfg)]
    write_outputs(kept, len(jobs), len(watchlist), errors)
    print(f"{len(jobs)} postings from {len(watchlist)} boards -> {len(kept)} kept "
          f"({sum(j.priority == 'P0' for j in kept)} P0). See output/digest.md")
    return kept


if __name__ == "__main__":
    main()
