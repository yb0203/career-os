"""Daily run: all sources -> gates -> dedupe -> score -> live-check -> output/jobs.csv + output/digest.md

    python -m pipeline.run                     # everything
    python -m pipeline.run --only linkedin yc  # just these sources ("ats" = company watchlist)
    python -m pipeline.run --company Zeta      # one watchlist company
"""
from __future__ import annotations

import argparse
import json
import collections
import concurrent.futures as cf
import csv
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pipeline import gates, scorer
from pipeline.fetchers import FETCHERS
from pipeline.models import Job
from pipeline.sources import SOURCES, session

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
ATS = set(FETCHERS)
CLOSED_MARKERS = ("no longer accepting applications", "this job is no longer available",
                  "job has expired", "position has been filled", "job not found")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())


def collect(watchlist: list[dict], sources: dict, terms: list[str]):
    """Run every ATS board and every enabled source in parallel."""
    tasks = {f"ats:{e['name']}": (FETCHERS[e["ats"]], (e["name"], e["slug"])) for e in watchlist}
    for name, params in sources.items():
        tasks[name] = (SOURCES[name], (params, terms))

    jobs, errors, counts = [], [], collections.Counter()
    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(fn, *args): name for name, (fn, args) in tasks.items()}
        for fut in cf.as_completed(futures):
            name = futures[fut]
            try:
                got = fut.result()
            except Exception as exc:  # one broken source shouldn't sink the run
                errors.append(f"{name}: {str(exc)[:160]}")
                continue
            jobs.extend(got)
            counts["ats" if name.startswith("ats:") else name] += len(got)
    return jobs, errors, counts


def dedupe(jobs: list[Job]) -> list[Job]:
    """Same company + title from several sources -> keep the most trustworthy copy."""
    def rank(j: Job):
        return (j.source not in ATS, j.posted_at is None, -len(j.description))

    best: dict[str, Job] = {}
    for j in sorted(jobs, key=rank):
        key = j.id
        if key not in best:
            best[key] = j
        else:
            best[key].reasons.append(f"also on {j.source.split(':')[0]}")
    return list(best.values())


def is_live(job: Job) -> bool:
    try:
        r = session().get(job.url, timeout=20, allow_redirects=True)
    except Exception:
        return False
    if r.status_code in (403, 429, 999):  # blocked / rate-limited: can't tell, so keep it
        return True
    return r.status_code < 400 and not any(m in r.text.lower() for m in CLOSED_MARKERS)


def verify_live(jobs: list[Job]) -> list[Job]:
    """ATS API postings are live by definition; check everything else."""
    to_check = [j for j in jobs if j.source not in ATS]
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        dead = {id(j) for j, ok in zip(to_check, pool.map(is_live, to_check)) if not ok}
    return [j for j in jobs if id(j) not in dead]


def write_outputs(kept: list[Job], scanned: int, counts: collections.Counter,
                  errors: list[str], dropped_dead: int) -> None:
    OUT.mkdir(exist_ok=True)
    kept.sort(key=lambda j: (-j.score, j.age_days if j.age_days is not None else 99))
    fields = ["id", "priority", "score", "lane", "company", "title", "location", "posted_at",
              "source", "apply_via", "url", "employment_type", "remote", "reasons"]
    with (OUT / "jobs.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for j in kept:
            w.writerow(j.to_row())

    today = datetime.now(timezone.utc).date().isoformat()
    by_source = collections.Counter(j.source.split(":")[0] for j in kept)
    lines = [
        f"# Daily job digest — {today}",
        "",
        f"Scanned **{scanned:,}** live postings from **{len(counts)}** sources → "
        f"**{len(kept)}** passed every gate "
        f"({sum(j.priority == 'P0' for j in kept)} P0, {sum(j.priority == 'P1' for j in kept)} P1, "
        f"{sum(j.priority == 'P2' for j in kept)} P2). {dropped_dead} dead links removed.",
        "",
        "| Pri | Score | Lane | Company | Role | Location | Posted | Source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for j in kept:
        if j.priority == "P2":
            continue
        posted = j.posted_at.date().isoformat() if j.posted_at else "?"
        loc = j.location if len(j.location) <= 60 else j.location[:57] + "…"
        lines.append(f"| {j.priority} | {j.score} | {j.lane} | {j.company} | "
                     f"[{j.title}]({j.url}) | {loc} | {posted} | {j.source.split(':')[0]} |")
    lines += ["", "P2 roles are in [`jobs.csv`](jobs.csv).", "",
              "<details><summary>Postings scanned / kept per source</summary>", "",
              "| Source | Scanned | Kept |", "|---|---|---|"]
    for name, n in counts.most_common():
        lines.append(f"| {name} | {n:,} | {by_source.get(name, 0) + (sum(by_source[a] for a in ATS) if name == 'ats' else 0)} |")
    lines += ["", "</details>"]
    if errors:
        lines += ["", f"<details><summary>{len(errors)} source errors</summary>", ""]
        lines += [f"- {e}" for e in errors]
        lines += ["", "</details>"]
    (OUT / "digest.md").write_text("\n".join(lines) + "\n")


def main(argv=None) -> list[Job]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", help="source names to run; 'ats' = the company watchlist")
    ap.add_argument("--company", help="only this watchlist company (implies --only ats)")
    ap.add_argument("--no-verify", action="store_true", help="skip the live-URL check")
    args = ap.parse_args(argv)

    cfg = load_yaml("config/lanes.yaml")
    src_cfg = load_yaml("config/sources.yaml")
    watchlist = load_yaml("watchlist.yaml")["companies"]
    sources = {k: v for k, v in src_cfg["sources"].items() if v.get("enabled", True)}

    only = set(args.only or [])
    if args.company:
        only = {"ats"}
        watchlist = [c for c in watchlist if c["name"].lower() == args.company.lower()]
    if only:
        sources = {k: v for k, v in sources.items() if k in only}
        if "ats" not in only:
            watchlist = []

    jobs, errors, counts = collect(watchlist, sources, src_cfg["search_terms"])
    passed = dedupe([j for j in jobs if gates.apply(j, cfg)])
    live = passed if args.no_verify else verify_live(passed)
    kept = [scorer.score(j, cfg) for j in live]
    write_outputs(kept, len(jobs), counts, errors, len(passed) - len(live))
    # Which sources actually answered this run: the sheet sync only flags rows from these as
    # "no longer listed", so a rate-limited source (LinkedIn from CI) doesn't close its rows.
    failed = {e.split(":")[0] for e in errors if not e.startswith("ats:")}
    scanned = sorted((set(sources) - failed) | ({"ats"} if watchlist else set()))
    (OUT / "run_meta.json").write_text(json.dumps({"scanned": scanned, "failed": sorted(failed)}, indent=1) + "\n")
    print(f"{len(jobs):,} postings from {len(counts)} sources -> {len(kept)} kept "
          f"({sum(j.priority == 'P0' for j in kept)} P0, {sum(j.priority == 'P1' for j in kept)} P1), "
          f"{len(passed) - len(live)} dead links dropped. See output/digest.md")
    for e in errors:
        print("  error:", e)
    return kept


if __name__ == "__main__":
    main()
