"""Build the sheet's "Today's Batch" tab: the 20-30 openings to apply to today, with 6-8+ strong ones on top.

    python -m pipeline.daily_batch

Rules (Yashvi, 2026-10-26/29): 20-30 applications a day, at least 6-8 genuinely strong. Roles are product and growth
flavoured; location is open (India anywhere, remote, and abroad where visa/relocation support is stated).
The batch is rebuilt after every sync; it never changes Status or Notes in "Openings"/"Europe".

  - India rows come from "Openings" (Status New, Tier Strong/Medium/Exploratory; empty tiers are computed).
  - Foreign rows come from "Europe" (Status New, open, product/growth roles with sponsor / relocation /
    remote-worldwide / remote-check signals), tiered with `classify_foreign`.
  - Anything already Applied / Interviewing / Rejected / In Progress / Skip (same company + role) is dropped.
  - Strong rows come first (direct no-login ATS first), then Medium, then Exploratory.
"""
from __future__ import annotations

import html
import json
import os
import re

import yaml

from pipeline.pm_targets import lane, years_asked
from pipeline.queue import who
from pipeline.run import ROOT
from pipeline.sheets import client
from pipeline.tiers import CORE, classify, classify_foreign, foreign_years

TAB = "Today's Batch"
HEADER = ["#", "Tier", "Region", "Company", "Role", "Location", "Years asked", "Route", "Resume lane", "Visa / remote",
          "Apply link", "Before applying", "ID"]
DONE = {"Applied", "Interviewing", "Rejected", "In Progress", "Skip", "Closed", "Offer"}
TIER_RANK = {"Strong": 0, "Medium": 1, "Exploratory": 2}
ROUTE_RANK = {"Claude · fill": 0, "Claude · verify+fill": 1, "Yashvi · Instahyre": 2, "Yashvi · Cutshort": 2,
              "Yashvi · login": 3, "Decide": 4}
TOTAL, MIN_STRONG, MAX_STRONG, MAX_FOREIGN = 30, 8, 12, 6


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _num(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def candidates(openings: list[dict], europe: list[dict], login: set[str]) -> list[dict]:
    done = {(norm(r["Company"]), norm(r["Role"])) for r in openings + europe if r.get("Status") in DONE}
    out: list[dict] = []
    for r in openings:
        if r.get("Status") not in ("New", "") or str(r.get("Open", "Yes")).lower() == "no":
            continue
        if (norm(r["Company"]), norm(r["Role"])) in done:
            continue
        if not CORE.search(r.get("Role", "")) or re.search(r"intern(ship)?\b|business development|\bsales\b", r.get("Role", ""), re.I):
            continue   # the batch is product / growth / founder's-office roles only
        tier = r.get("Tier") or classify(r.get("Role", ""), str(r.get("Location", "")), str(r.get("Why", "")))
        if tier not in TIER_RANK:
            continue
        route, link = who(r, login)
        yrs = years_asked(str(r.get("Why", "")))
        loc = str(r.get("Location", ""))
        region = "Remote" if re.search(r"remote|anywhere|worldwide", loc, re.I) else "India"
        out.append(dict(tier=tier, region=region, company=r["Company"], role=r["Role"], location=loc, years=yrs,
                        route=route, lane=lane(r["Role"], str(r.get("Why", ""))), visa="", link=link,
                        score=_num(r.get("Score")), id=r.get("ID", "")))
    for r in europe:
        if r.get("Status") not in ("New", "") or str(r.get("Open", "Yes")).lower() == "no":
            continue
        if (norm(r["Company"]), norm(r["Role"])) in done:
            continue
        visa, remote = str(r.get("Visa/Relocation", "")), str(r.get("Remote", ""))
        tier = classify_foreign(r["Role"], str(r.get("Family", "")), visa, remote, str(r.get("Why", "")))
        if tier not in TIER_RANK:
            continue
        direct = str(r.get("Apply method", "")).startswith("Direct")
        out.append(dict(tier=tier, region="Foreign", company=r["Company"], role=r["Role"],
                        location=str(r.get("Country", "")), years=foreign_years(str(r.get("Why", ""))),
                        route="Claude · fill" if direct else "Claude · verify+fill",
                        lane=lane(r["Role"], str(r.get("Why", ""))),
                        visa=f"{visa}{' · remote' if remote == 'Yes' else ''}", link=r.get("Apply link", ""),
                        score=_num(r.get("Score")), id=r.get("ID", "")))
    return out


def select(cands: list[dict], total: int = TOTAL, min_strong: int = MIN_STRONG, max_strong: int = MAX_STRONG,
           max_foreign: int = MAX_FOREIGN) -> list[dict]:
    key = lambda c: (TIER_RANK[c["tier"]], ROUTE_RANK.get(c["route"], 5), -c["score"])
    ordered = sorted(cands, key=key)
    picked: list[dict] = []
    foreign = 0
    seen_company: dict[str, int] = {}
    for c in ordered:
        if len(picked) >= total:
            break
        if c["region"] == "Foreign" and foreign >= max_foreign:
            continue
        if c["tier"] == "Strong" and sum(p["tier"] == "Strong" for p in picked) >= max_strong:
            continue
        if seen_company.get(norm(c["company"]), 0) >= 1:   # one role per company per day
            continue
        picked.append(c)
        seen_company[norm(c["company"])] = 1
        foreign += c["region"] == "Foreign"
    picked.sort(key=key)
    return picked


def _get(url: str) -> str:
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return r.text if r.ok else ""
    except Exception:
        return ""


YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*years?", re.I)


def jd_text(url: str) -> str:
    """Job description text for the ATS boards that expose a public API; empty when unknown."""
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    if m:
        try:
            d = json.loads(_get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}"))
            return d.get("descriptionPlain", "") + " " + " ".join(x.get("content", "") for x in d.get("lists", []))
        except Exception:
            return ""
    m = re.search(r"greenhouse\.io/(?:[^/]+/)?([^/?]+)/jobs/(\d+)", url)
    if m:
        try:
            d = json.loads(_get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}"))
            return re.sub(r"<[^>]+>", " ", html.unescape(d.get("content", "")))
        except Exception:
            return ""
    m = re.search(r"ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    if m:
        try:
            for j in json.loads(_get(f"https://api.ashbyhq.com/posting-api/job-board/{m[1]}"))["jobs"]:
                if j["id"] == m[2]:
                    return j.get("descriptionPlain", "")
        except Exception:
            return ""
    m = re.search(r"https://([^/]+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)", url)
    if m:
        try:
            tenant = m[1].split(".")[0]
            d = json.loads(_get(f"https://{m[1]}.myworkdayjobs.com/wday/cxs/{tenant}/{m[2]}{m[3]}"))
            return re.sub(r"<[^>]+>", " ", html.unescape(d["jobPostingInfo"].get("jobDescription", "")))
        except Exception:
            return ""
    m = re.search(r"apply\.workable\.com/(?:([^/]+)/)?j/([A-Za-z0-9]+)", url)
    if m and m[1]:
        try:
            d = json.loads(_get(f"https://apply.workable.com/api/v1/accounts/{m[1]}/jobs/{m[2]}"))
            return re.sub(r"<[^>]+>", " ", html.unescape(d.get("description", "") + " " + d.get("requirements", "")))
        except Exception:
            return ""
    return ""


def min_years(text: str):
    """The lowest 'N years' figure that looks like a requirement (e.g. '3+ years of product management')."""
    best = None
    for m in YEARS_RE.finditer(text or ""):
        ctx = text[max(0, m.start() - 60): m.end() + 60].lower()
        if not re.search(r"experience|exp\b|product management|as a (?:product )?manager|in product", ctx) or \
                re.search(r"\bago\b|founded|since |in business|customers|funding", ctx):
            continue
        n = int(m.group(1))
        if 0 < n <= 20:
            best = n if best is None else min(best, n)
    return best


def enrich_years(cands: list[dict], limit: int = 60) -> None:
    """Fill 'years' from the JD for the first `limit` candidates (best tiers first) and re-tier by real years."""
    ordered = sorted(cands, key=lambda c: (TIER_RANK[c["tier"]], ROUTE_RANK.get(c["route"], 5), -c["score"]))
    for c in ordered[:limit]:
        if c["years"] is None and c["link"]:
            c["years"] = min_years(jd_text(c["link"]))
        if c["years"] is not None and c["tier"] == "Strong" and c["years"] > 4:
            c["tier"] = "Medium" if c["years"] <= 6 else "Exploratory"
        elif c["years"] is not None and c["tier"] == "Medium" and c["years"] > 8:
            c["tier"] = "Exploratory"


def to_values(batch: list[dict]) -> list[list]:
    rows = [HEADER]
    for i, c in enumerate(batch, 1):
        todo = "Find a named contact; tailor resume to JD keywords" if c["tier"] == "Strong" else "Tailor resume if time allows"
        rows.append([i, c["tier"], c["region"], c["company"], c["role"], c["location"],
                     c["years"] if c["years"] is not None else "?", c["route"], c["lane"], c["visa"], c["link"], todo, c["id"]])
    return rows


def main():
    cfg = yaml.safe_load((ROOT / "config/sheet.yaml").read_text())
    sh = client().open_by_key(os.environ.get("SHEET_ID") or cfg["spreadsheet_id"])
    openings = sh.worksheet("Openings").get_all_records(numericise_ignore=["all"])
    europe = sh.worksheet("Europe").get_all_records(numericise_ignore=["all"])
    cands = candidates(openings, europe, set(cfg.get("login_companies", [])))
    enrich_years(cands)
    batch = select(cands)
    values = to_values(batch)
    try:
        ws = sh.worksheet(TAB)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(TAB, rows=len(values) + 20, cols=len(HEADER))
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    ws.format("A1:M1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.89, "green": 0.93, "blue": 0.99}})
    ws.freeze(rows=1)
    strong = sum(c["tier"] == "Strong" for c in batch)
    foreign = sum(c["region"] == "Foreign" for c in batch)
    print(f"Today's Batch: {len(batch)} roles, {strong} strong, {foreign} foreign"
          + ("" if strong >= MIN_STRONG else f" (only {strong} strong available; target {MIN_STRONG})"))


if __name__ == "__main__":
    main()
