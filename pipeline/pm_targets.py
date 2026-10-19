"""PM-only views for the interview push: "PM Targets" (ranked), "Applied" (tracker), "Outreach" (people).

    python -m pipeline.pm_targets

PM Targets: open Product Management roles at Yashvi's level (APM / PM / AI PM / Technical PM), ranked by fit,
with the resume lane to use and how many people she has already contacted at that company.
Applied: every application (main + Europe tabs) with status, date, via, follow-up date and company contact count.
Outreach: hand-edited log of people (created once, never overwritten).
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta

import yaml

from pipeline.run import ROOT
from pipeline.sheets import client

PM_TITLE = re.compile(r"\b(product manager|product owner|associate product|apm\b|pm\s*[-–,(]|product lead)", re.I)
NOT_PM = re.compile(r"program manager|project manager|product marketing|product design|product analyst|"
                    r"product support|product operations|product specialist|sales|account manager|contributor|intern\b", re.I)
TOO_SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|director|head|vp|group|chief)\b", re.I)
OUT_OF_SCOPE_CITY = re.compile(r"mumbai|pune|hyderabad|chennai|kolkata", re.I)
AI = re.compile(r"\b(ai|llm|genai|gen ai|agent|agentic|ml|machine learning|copilot|voice ai)\b", re.I)
FINTECH = re.compile(r"fintech|payment|bank|lending|credit|insur|invest|wealth|upi|trading|finance|loan|cards?\b", re.I)
PLATFORM = re.compile(r"platform|api|developer|infra|technical|b2b|saas|enterprise|security|data", re.I)
CONSUMER_GROWTH = re.compile(r"growth|b2c|consumer|marketplace|d2c|e-?commerce|ads?\b", re.I)
SKIP_STATUS = {"Applied", "Interviewing", "Rejected", "Offer", "Skip", "Closed"}

PM_HEADER = ["Rank", "Fit", "Company", "Role", "Location", "Years asked", "Resume lane", "Route", "Apply link",
             "People contacted", "Status", "Why it fits", "ID"]
APPLIED_HEADER = ["Company", "Role", "Status", "Applied on", "Via", "Resume / lane", "People contacted",
                  "Follow-up due", "Tab", "Notes"]
OUTREACH_HEADER = ["Company", "Role", "Person", "Title", "Where found", "LinkedIn URL", "Email", "Channel",
                   "Sent on", "Reply", "Follow-up due", "Notes"]


def years_asked(why: str) -> int | None:
    m = re.search(r"(\d+)\+?\s*yrs? asked", why or "")
    return int(m.group(1)) if m else None


def lane(role: str, text: str) -> str:
    t = f"{role} {text}"
    if FINTECH.search(t) and not AI.search(role):
        return "Fintech PM"
    if AI.search(role) or (AI.search(t) and not FINTECH.search(t)):
        return "AI PM"
    if re.search(r"technical|platform|api|developer|infra", role, re.I):
        return "Technical PM"
    if FINTECH.search(t):
        return "Fintech PM"
    return "Product Manager"


def fit(row: dict) -> tuple[int, str, int | None]:
    role, why = row.get("Role", ""), str(row.get("Why", ""))
    text = f"{role} {why} {row.get('Company', '')}"
    yrs = years_asked(why)
    score = int(row.get("Score") or 0) // 4
    reasons = []
    if AI.search(text):
        score += 22; reasons.append("AI/agents")
    if FINTECH.search(text):
        score += 18; reasons.append("fintech/payments")
    if PLATFORM.search(text):
        score += 10; reasons.append("platform/technical")
    if yrs is not None:
        if 1 <= yrs <= 3:
            score += 20; reasons.append(f"{yrs}+ yrs asked (her level)")
        elif yrs == 4:
            score += 8
        elif yrs >= 5:
            score -= 25
    if re.search(r"remote", f"{row.get('Location', '')} {role}", re.I):
        score += 6
    if CONSUMER_GROWTH.search(role):
        score -= 10; reasons.append("consumer/growth lean")
    if re.search(r"\bassociate\b|\bapm\b", role, re.I):
        score += 6
    return score, ", ".join(reasons), yrs


def contacted_by_company(outreach: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in outreach:
        if str(r.get("Sent on", "")).strip():
            key = re.sub(r"[^a-z0-9]", "", str(r.get("Company", "")).lower())
            out[key] = out.get(key, 0) + 1
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def build_pm(rows: list[dict], contacted: dict[str, int]) -> list[list]:
    seen_ids, picked = set(), []
    for r in rows:
        if r.get("Status") in SKIP_STATUS or str(r.get("Open", "Yes")).lower() == "no":
            continue
        role = r.get("Role", "")
        if not PM_TITLE.search(role) or NOT_PM.search(role) or TOO_SENIOR.search(role):
            continue
        if OUT_OF_SCOPE_CITY.search(str(r.get("Location", ""))) and not re.search(r"bengal|bangal|remote|gurg|noida|delhi", str(r.get("Location", "")), re.I):
            continue
        if r["ID"] in seen_ids:
            continue
        seen_ids.add(r["ID"])
        score, reasons, yrs = fit(r)
        if yrs is not None and yrs >= 6:
            continue
        picked.append((score, reasons, yrs, r))
    picked.sort(key=lambda x: -x[0])
    out = [PM_HEADER]
    for i, (score, reasons, yrs, r) in enumerate(picked[:120], 1):
        src = r.get("Source", "")
        route = "Instahyre (you)" if src == "instahyre" else "Cutshort (you)" if src == "cutshort" else \
                "Weekday (needs sign-in)" if "weekday" in str(r.get("URL", "")) else "LinkedIn / company page" if "linkedin" in str(r.get("URL", "")) else "Company ATS (Claude fills)"
        out.append([i, score, r["Company"], r["Role"], r.get("Location", ""), yrs if yrs is not None else "?",
                    lane(r["Role"], r.get("Why", "")), route, r.get("URL", ""),
                    contacted.get(norm(r["Company"]), 0), r.get("Status") or "New", reasons, r["ID"]])
    return out


def build_applied(openings: list[dict], europe: list[dict], contacted: dict[str, int]) -> list[list]:
    out = [APPLIED_HEADER]
    for tab, rows in (("Openings", openings), ("Europe", europe)):
        for r in rows:
            st = r.get("Status")
            if st not in ("Applied", "Interviewing", "Rejected", "Offer"):
                continue
            note = str(r.get("Notes", ""))
            m = re.search(r"Applied (\d{4}-\d\d-\d\d)(?: \(([^)]*)\))?", note)
            applied = m.group(1) if m else ""
            via = m.group(2) if m and m.group(2) else r.get("Apply via", "")
            fu = ""
            if applied and st == "Applied":
                fu = (datetime.strptime(applied, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
            out.append([r["Company"], r["Role"], st, applied, via, "", contacted.get(norm(r["Company"]), 0), fu, tab, note[:140]])
    out[1:] = sorted(out[1:], key=lambda x: (x[2] != "Interviewing", x[3] or "0"), reverse=False)
    return out


def write(sh, title: str, values: list[list], widths: list[int]) -> None:
    try:
        ws = sh.worksheet(title)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(title=title, rows=max(len(values) + 20, 100), cols=len(values[0]))
    ws.resize(rows=max(len(values) + 20, 100), cols=len(values[0]))
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    reqs = [{"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                           "backgroundColor": {"red": 0.89, "green": 0.93, "blue": 0.99}}},
                            "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
            {"updateSheetProperties": {"properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
                                       "fields": "gridProperties.frozenRowCount"}}]
    for i, w in enumerate(widths):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                                                   "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    sh.batch_update({"requests": reqs})


def main():
    cfg = yaml.safe_load((ROOT / "config/sheet.yaml").read_text())
    sh = client().open_by_key(os.environ.get("SHEET_ID") or cfg["spreadsheet_id"])
    openings = sh.worksheet("Openings").get_all_records(numericise_ignore=["all"])
    europe = sh.worksheet("Europe").get_all_records(numericise_ignore=["all"])
    titles = {w.title for w in sh.worksheets()}
    if "Outreach" not in titles:
        ws = sh.add_worksheet(title="Outreach", rows=300, cols=len(OUTREACH_HEADER))
        ws.update(values=[OUTREACH_HEADER], range_name="A1")
        ws.format("A1:L1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.89, "green": 0.93, "blue": 0.99}})
        ws.freeze(rows=1)
    outreach = sh.worksheet("Outreach").get_all_records(numericise_ignore=["all"])
    contacted = contacted_by_company(outreach)
    pm = build_pm(openings + europe, contacted)
    write(sh, "PM Targets", pm, [50, 50, 160, 260, 130, 80, 110, 160, 330, 90, 90, 220, 90])
    applied = build_applied(openings, europe, contacted)
    write(sh, "Applied", applied, [160, 260, 100, 100, 200, 110, 100, 100, 80, 360])
    print(f"PM Targets: {len(pm) - 1} roles; Applied: {len(applied) - 1} rows; Outreach rows: {len(outreach)}")


if __name__ == "__main__":
    main()
