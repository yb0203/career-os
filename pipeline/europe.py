"""Separate Europe job search: sourcing, classification and scoring.

    from pipeline.europe import fetch_all
    rows, scanned, stats = fetch_all()

A role is kept ONLY if it is a tech role Yashvi's profile fits (engineering or product, junior to
mid), is in Europe, and either offers visa sponsorship / relocation support or is fully remote and
open to India or worldwide. Everything else is dropped. Config: config/europe.yaml.
Source status (used / manual / login / blocked / dead): config/europe_sources.md.
"""
from __future__ import annotations

import concurrent.futures as cf
import functools
import html
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
import yaml

from pipeline import fetchers as f
from pipeline.europe_ats import ATS_FETCHERS
from pipeline.models import Job
from pipeline.run import ROOT
from pipeline.sources import remote_boards, session

CONFIG = ROOT / "config" / "europe.yaml"
APPLY_ORDER = {"Direct (no login)": 0, "Account needed": 1, "Aggregator": 2}
SIGNAL_ORDER = {"sponsor": 0, "relocation": 1, "remote-worldwide": 2, "remote-check": 3}
ARBEITNOW_HOSTS = {  # host -> country assumed when a posting names only a city we do not know
    "https://www.arbeitnow.com": "Germany", "https://www.arbeitnow.co.uk": "United Kingdom",
    "https://www.arbeitnow.nl": "Netherlands", "https://www.arbeitnow.ch": "Switzerland",
    "https://www.arbeitnow.fr": "France",
}
ARBEITNOW_PAGES = 4  # 100-300 jobs per page on .com, newest first (other hosts have 1-2 pages)
RELOCATE_PAGES = 6
BERLIN_FEEDS = ["https://berlinstartupjobs.com/engineering/feed/"]


# ------------------------------------------------------------------ config
@functools.lru_cache(maxsize=1)
def load_config() -> dict:
    return compile_config(yaml.safe_load(CONFIG.read_text()))


def _rx(patterns) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


def compile_config(raw: dict) -> dict:
    cfg = dict(raw)
    t = raw["titles"]
    cfg["_eng"], cfg["_prod"] = _rx(t["engineering"]), _rx(t["product"])
    cfg["_excl"], cfg["_senior"] = _rx(t["exclude"]), _rx(t["seniority_exclude"])
    cfg["_junior"], cfg["_ai"] = _rx(t["junior_boost"]), re.compile(t["ai_title"], re.I)
    s = raw["sponsorship"]
    cfg["_neg_strong"], cfg["_neg_soft"] = _rx(s["negative_strong"]), _rx(s["negative_soft"])
    cfg["_pos"] = _rx(s["positive"])
    cfg["_visa_words"], cfg["_negation"] = re.compile(s["visa_words"], re.I), re.compile(s["negation_words"], re.I)
    r = raw["remote"]
    cfg["_worldwide"], cfg["_europe"], cfg["_remote_excl"] = _rx(r["worldwide"]), _rx(r["europe"]), _rx(r["excluded"])
    cfg["_countries"] = []
    for name, c in raw["countries"].items():
        aliases = sorted(c["aliases"], key=len, reverse=True)
        pat = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(a) for a in aliases) + r")(?![\w])", re.I)
        cfg["_countries"].append((name, bool(c.get("nordic")), c["code"], pat))
    cfg["_codes"] = {c["code"]: n for n, c in raw["countries"].items()}
    return cfg


# ------------------------------------------------------------------ small helpers
def clean_text(value) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def apply_method(url: str, cfg: dict, source: str = "") -> str:
    host = (urlparse(url or "").hostname or "").lower()
    if "arbeitnow." in host:  # country-specific domains: .com .co.uk .nl .ch .fr
        return "Aggregator"
    hosts = cfg["apply_hosts"]
    for label, key in (("Account needed", "account"), ("Direct (no login)", "direct"), ("Aggregator", "aggregator")):
        if any(host == h or host.endswith("." + h) for h in hosts[key]):
            return label
    # Unknown host: the company's own careers page / form counts as direct.
    return "Direct (no login)" if host else "Aggregator"


def find_countries(location: str, cfg: dict, source: str = "") -> list[tuple[str, bool]]:
    """European countries named in a location string, in order of appearance."""
    loc = location or ""
    if source == "smartrecruiters":  # "Berlin, BE, DE": the trailing token is the ISO country code
        for part in loc.split(" / "):
            m = re.search(r",\s*([A-Z]{2})\s*$", part.strip())
            if m and m.group(1) in cfg["_codes"]:
                loc += " " + cfg["_codes"][m.group(1)]
    found: list[tuple[int, str, bool]] = []
    for name, nordic, _code, pat in cfg["_countries"]:
        m = pat.search(loc)
        if m:
            found.append((m.start(), name, nordic))
    found.sort()
    return [(n, nd) for _, n, nd in found]


def required_years(text: str) -> int:
    """Highest 'minimum years of experience' a posting asks for (0 if it names none)."""
    best = 0
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs)\b", text, re.I):
        ctx = text[max(0, m.start() - 60): m.end() + 60].lower()
        if "experience" in ctx or "exp" in ctx:
            best = max(best, int(m.group(1)))
    return best


def sponsorship_signal(text: str, cfg: dict) -> tuple[str | None, str, str]:
    """-> (signal, evidence, verdict) with signal in {sponsor, relocation, None} and
    verdict in {ok, rejected_strong, rejected_soft}."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n|•|·", text) if s.strip()]
    positive, soft = None, False
    for s in sentences:
        if cfg["_neg_strong"].search(s):
            return None, s[:140], "rejected_strong"
        if cfg["_neg_soft"].search(s):
            soft = True
        if positive is None and cfg["_pos"].search(s):
            m = cfg["_pos"].search(s)
            window = s[max(0, m.start() - 60): m.end() + 40]
            if cfg["_negation"].search(window):
                continue  # "no relocation support" style: not a positive
            kind = "sponsor" if cfg["_visa_words"].search(s) else "relocation"
            positive = (kind, s[max(0, m.start() - 50): m.end() + 60].strip())
    if positive:
        return positive[0], positive[1], "ok-soft" if soft else "ok"
    return None, "", "rejected_soft" if soft else "ok"


def remote_signal(job: Job, countries: list, cfg: dict, text_desc: str) -> str | None:
    """'remote-worldwide' / 'remote-check' / None, from where the posting says remote workers may live."""
    loc = f"{job.location} {job.title}"
    is_remote = job.remote is True or re.search(r"\b(remote|work from home|distributed|anywhere)\b", loc, re.I)
    if not is_remote:
        return None
    if re.search(r"\bhybrid\b", loc, re.I) and job.remote is not True and not re.search(r"\bremote\b", loc, re.I):
        return None
    world_loc = cfg["_worldwide"].search(job.location) or cfg["_worldwide"].search(job.title)
    world_desc = re.search(r"work from anywhere|anywhere in the world|open to candidates (?:from|in) (?:any|all)|"
                           r"fully remote.{0,40}worldwide|remote.{0,20}worldwide", text_desc[:3000], re.I)
    # A posting pinned to named countries is "EU remote" at best, whatever its blurb says.
    has_world = world_loc or (world_desc and not countries)
    has_europe = cfg["_europe"].search(loc) or len({n for n, _ in countries}) >= 2
    restricted = cfg["_remote_excl"].search(job.location) and not (has_world or has_europe)
    if restricted:
        return None
    if has_world:
        return "remote-worldwide"
    if has_europe:
        return "remote-check"
    return None


# ------------------------------------------------------------------ classification
def classify(job: Job, cfg: dict, hint: str | None = None) -> dict | None:
    """Turn one posting into a sheet row, or None if it should not be on the Europe tab."""
    title = clean_text(job.title)
    if not title or cfg["_excl"].search(title) or cfg["_senior"].search(title):
        return None
    eng, prod = bool(cfg["_eng"].search(title)), bool(cfg["_prod"].search(title))
    if not (eng or prod):
        return None
    family = "Product" if prod else "Engineering"
    ai_title = bool(cfg["_ai"].search(title))
    if re.search(r"\bsolutions?\s+engineer", title, re.I) and not ai_title:
        return None  # only AI-flavoured solutions engineering is in scope
    if job.age_days is not None and job.age_days > cfg["max_age_days"]:
        return None

    desc = clean_text(job.description)
    if desc and required_years(desc) > cfg["max_years_required"]:
        return None

    countries = find_countries(job.location, cfg, job.source)
    text = f"{title}. {job.location}. {desc}"
    kind, evidence, verdict = sponsorship_signal(text, cfg)
    if hint and verdict != "rejected_strong":
        kind, verdict = (kind or hint), "ok"
        evidence = evidence or f"listed with {hint} flag on {job.source}"
    if verdict == "rejected_strong":
        return None
    remote_kind = remote_signal(job, countries, cfg, desc)

    signal = None
    if kind and countries and verdict in ("ok", "ok-soft"):
        signal = kind
    elif remote_kind:
        signal = remote_kind
        if cfg["_neg_soft"].search(desc) and remote_kind == "remote-worldwide":
            signal = "remote-check"
    if not signal:
        return None
    if not countries and signal not in ("remote-worldwide", "remote-check"):
        return None

    # --- presentation fields
    nordic = any(nd for _, nd in countries)
    if countries:
        country = " / ".join(n for n, _ in countries[:4])
    else:
        country = "Worldwide (remote)" if signal == "remote-worldwide" else "Europe (remote)"
    remote = "Yes" if (job.remote is True or remote_kind) else ("Hybrid" if re.search(r"hybrid", job.location, re.I) else "No")
    ai_desc = len(re.findall(r"\b(llms?|generative ai|genai|machine learning|large language|agentic|rag)\b", desc, re.I)) >= 3
    ai = "Yes" if (ai_title or ai_desc) else "No"
    method = apply_method(job.url, cfg, job.source)

    # --- score
    score = 40
    why: list[str] = []
    if ai_title:
        score += 25; why.append("AI/LLM title")
    elif ai_desc:
        score += 10; why.append("AI-heavy description")
    if signal in ("sponsor", "relocation"):
        score += 15; why.append("visa sponsorship stated" if signal == "sponsor" else "relocation support stated")
        if verdict == "ok-soft":
            score -= 5; why.append("also says right-to-work: verify")
    elif signal == "remote-worldwide":
        score += 12; why.append("remote, open worldwide")
    else:
        score += 3; why.append("EU/EMEA remote: check working rights")
    if method == "Direct (no login)":
        score += 10; why.append(f"direct apply ({job.apply_via or 'company form'})")
    elif method == "Account needed":
        why.append("account needed to apply")
    else:
        score += 2; why.append("aggregator link only")
    if nordic:
        score += 8; why.append("Nordics")
    if cfg["_junior"].search(title):
        score += 8; why.append("junior-friendly title")
    years = required_years(desc) if desc else 0
    if 0 < years <= 3:
        score += 5; why.append(f"asks ~{years} yrs")
    elif years > 3:
        score -= 5 if years == 4 else 10; why.append(f"asks {years}+ yrs")
    if evidence and signal in ("sponsor", "relocation"):
        why.append(f'"{evidence[:90]}"')

    return {
        "ID": job.id, "Score": min(score, 100), "Company": clean_text(job.company), "Role": title,
        "Family": family, "AI": ai, "Country": country, "Nordic": "Yes" if nordic else "No",
        "Visa/Relocation": signal, "Remote": remote, "Apply method": method, "Apply link": job.url,
        "Why": "; ".join(why), "Posted": job.posted_at.date().isoformat() if job.posted_at else "",
        "Source": job.source.split(":")[0], "_countries": [n for n, _ in countries],
    }


def merge_duplicates(rows: list[dict]) -> list[dict]:
    """One row per company+title (Job.id): keep the best-apply copy, union the countries."""
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["ID"])
        if cur is None:
            best[r["ID"]] = r
            continue
        rank = lambda x: (APPLY_ORDER[x["Apply method"]], SIGNAL_ORDER[x["Visa/Relocation"]], -x["Score"])
        keep, other = (r, cur) if rank(r) < rank(cur) else (cur, r)
        merged = [c for c in keep["_countries"] + other["_countries"]]
        keep["_countries"] = list(dict.fromkeys(merged))
        if keep["_countries"]:
            keep["Country"] = " / ".join(keep["_countries"][:4])
        keep["Nordic"] = "Yes" if "Yes" in (keep["Nordic"], other["Nordic"]) else "No"
        if other["Source"] != keep["Source"]:
            keep["Source"] += f"+{other['Source']}"
        best[r["ID"]] = keep
    return sorted(best.values(), key=lambda r: (-r["Score"], r["Company"]))


# ------------------------------------------------------------------ sources
def _arbeitnow_job(j: dict, default_country: str) -> Job:
    ts = j.get("created_at")
    location = j.get("location", "")
    if location and not find_countries(location, load_config()):
        location += f", {default_country}"  # the .com board is German, the .co.uk board British
    return Job(
        company=j.get("company_name", ""), title=j.get("title", ""), url=j.get("url", ""),
        source="arbeitnow", apply_via="arbeitnow", location=location,
        remote=True if j.get("remote") else None,
        posted_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
        description=f.strip_html(j.get("description", "")), employment_type=", ".join(j.get("job_types") or []),
    )


def fetch_arbeitnow() -> list[Job]:
    """Public API (free, 'please do not abuse'): only the visa_sponsorship=true filter, a few pages."""
    jobs = []
    for host, default_country in ARBEITNOW_HOSTS.items():
        for page in range(1, ARBEITNOW_PAGES + 1):
            r = requests.get(f"{host}/api/job-board-api", params={"visa_sponsorship": "true", "page": page},
                             headers=f.HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json().get("data", [])
            jobs += [_arbeitnow_job(j, default_country) for j in data]
            if len(data) < 50:
                break
            time.sleep(1.5)
    return jobs


RELOCATE_ITEM = re.compile(
    r'<div class="job__title">\s*<a href="(/[a-z\-]+/[a-z\-]+/[a-z0-9\-]+/[a-z0-9\-]+)">\s*<b>(.*?)</b>', re.S)


def parse_relocate(page_html: str) -> list[Job]:
    jobs = []
    for path, title in RELOCATE_ITEM.findall(page_html):
        country, city, company_slug, _ = path.strip("/").split("/", 3)
        if country == "remote":
            continue  # their own paid-newsletter ad, not a posting
        jobs.append(Job(
            company=company_slug.replace("-", " ").title(), title=clean_text(title),
            url="https://relocate.me" + path, source="relocate.me", apply_via="relocate.me",
            location=f"{city.replace('-', ' ').title()}, {country.replace('-', ' ').title()}",
        ))
    return jobs


def fetch_relocate() -> list[Job]:
    """relocate.me lists only relocation-supported tech jobs; server-rendered, robots.txt allows it."""
    s, jobs, seen = session(), [], set()
    for page in range(1, RELOCATE_PAGES + 1):
        r = s.get("https://relocate.me/international-jobs", params={"page": page}, timeout=30)
        r.raise_for_status()
        batch = [j for j in parse_relocate(r.text) if j.url not in seen]
        if not batch:
            break
        seen.update(j.url for j in batch)
        jobs += batch
        time.sleep(1.5)
    return jobs


def fetch_berlin_startup_jobs() -> list[Job]:
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    jobs = []
    for feed in BERLIN_FEEDS:
        r = session().get(feed, timeout=30)
        r.raise_for_status()
        for item in ET.fromstring(r.content).iter("item"):
            raw = item.findtext("title", "")
            title, _, company = raw.rpartition(" // ")
            pub = item.findtext("pubDate")
            jobs.append(Job(
                company=company or item.findtext("{http://purl.org/dc/elements/1.1/}creator", ""),
                title=title or raw, url=item.findtext("link", ""), source="berlinstartupjobs",
                apply_via="berlinstartupjobs", location="Berlin, Germany",
                posted_at=parsedate_to_datetime(pub) if pub else None,
                description=f.strip_html(item.findtext("description", "")),
            ))
    return jobs


def fetch_remote_boards(cfg: dict) -> list[Job]:
    """Reuse the existing remote-board fetchers; classify() keeps only EU-or-worldwide remote roles."""
    terms = ["ai engineer", "machine learning engineer", "llm", "software engineer", "backend engineer",
             "product manager", "technical program manager", "python"]
    params = {"jobicy": {"tags": ["ai", "python", "java", "product", "engineering"]},
              "weworkremotely": {"feeds": ["remote-programming-jobs", "remote-product-jobs",
                                           "remote-back-end-programming-jobs", "remote-full-stack-programming-jobs"]}}
    jobs = []
    for name in cfg["remote_boards"]:
        try:
            jobs += getattr(remote_boards, name)(params.get(name, {}), terms)
        except Exception as exc:
            print(f"  ! {name}: {str(exc)[:100]}")
    return jobs


def _want(cfg: dict):
    """Cheap pre-filter so SmartRecruiters only fetches full descriptions for plausible roles."""
    def want(job: Job) -> bool:
        t = job.title
        return bool((cfg["_eng"].search(t) or cfg["_prod"].search(t)) and not cfg["_excl"].search(t)
                    and not cfg["_senior"].search(t) and find_countries(job.location, cfg, job.source))
    return want


def fetch_watchlist(cfg: dict) -> tuple[list[Job], list[str]]:
    """Every watchlist board, in parallel but one worker per ATS host family to stay polite."""
    entries = [(c, ats, slug) for c, spec in cfg["watchlist"].items() for ats, slug in spec.items()]
    want = _want(cfg)
    errors: list[str] = []

    def run(entry):
        company, ats, slug = entry
        return ATS_FETCHERS[ats](company, slug, want) if ats == "smartrecruiters" else ATS_FETCHERS[ats](company, slug)

    jobs: list[Job] = []
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(run, e): e for e in entries}
        for fut in cf.as_completed(futs):
            company, ats, slug = futs[fut]
            try:
                jobs += fut.result()
            except Exception as exc:
                errors.append(f"{company} ({ats}/{slug}): {str(exc)[:80]}")
    return jobs, errors


# ------------------------------------------------------------------ orchestration
def fetch_all(verbose: bool = True) -> tuple[list[dict], set[str], dict]:
    """-> (rows sorted by score, sources that answered this run, stats)."""
    cfg = load_config()
    raw: dict[str, tuple[list[Job], str | None]] = {}
    scanned: set[str] = set()
    stats = {"fetched": {}, "qualifying": {}, "errors": []}

    plan = [
        ("arbeitnow", fetch_arbeitnow, "sponsor"),
        ("relocate.me", fetch_relocate, "relocation"),
        ("berlinstartupjobs", fetch_berlin_startup_jobs, None),
        ("remote-boards", lambda: fetch_remote_boards(cfg), None),
    ]
    all_rows: list[dict] = []
    for name, fn, hint in plan:
        try:
            jobs = fn()
        except Exception as exc:
            stats["errors"].append(f"{name}: {str(exc)[:120]}")
            continue
        scanned.add(name)
        stats["fetched"][name] = len(jobs)
        rows = [r for r in (classify(j, cfg, hint) for j in jobs) if r]
        stats["qualifying"][name] = len(rows)
        all_rows += rows
        if verbose:
            print(f"  {name}: {len(jobs)} fetched, {len(rows)} qualifying")

    jobs, errors = fetch_watchlist(cfg)
    stats["errors"] += errors
    scanned.add("ats")
    rows = [r for r in (classify(j, cfg) for j in jobs) if r]
    stats["fetched"]["ats"], stats["qualifying"]["ats"] = len(jobs), len(rows)
    all_rows += rows
    if verbose:
        print(f"  ats watchlist: {len(jobs)} fetched, {len(rows)} qualifying, {len(errors)} board errors")

    merged = merge_duplicates(all_rows)
    return merged, scanned, stats


def check_watchlist() -> list[str]:
    """Report watchlist boards that no longer answer or list zero jobs (run before editing the list)."""
    cfg = load_config()
    dead = []
    for company, spec in cfg["watchlist"].items():
        for ats, slug in spec.items():
            try:
                n = len(ATS_FETCHERS[ats](company, slug))
            except Exception as exc:
                dead.append(f"{company} ({ats}/{slug}): {str(exc)[:60]}")
                continue
            if n == 0:
                dead.append(f"{company} ({ats}/{slug}): 0 jobs")
            time.sleep(0.3)
    return dead


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify every watchlist slug still has jobs")
    args = ap.parse_args()
    if args.check:
        dead = check_watchlist()
        print("\n".join(dead) or "all watchlist boards answer with jobs")
        return
    rows, _scanned, stats = fetch_all()
    print(f"{len(rows)} qualifying roles; errors: {stats['errors']}")


if __name__ == "__main__":
    main()
