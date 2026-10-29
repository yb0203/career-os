"""Rebuild the sheet's "Queue" tab: every pending opening, ranked, with who applies.

    python -m pipeline.queue

Reads the "Openings" tab (Status New/In Progress), ranks by Tier (Strong > Medium >
Exploratory > untiered), then by who applies, then by score. Rows are keyed by ID, so the
tab survives the daily re-sort of "Openings". Companies whose sites need a sign-in are listed
under `login_companies` in config/sheet.yaml.
"""
from __future__ import annotations

import os
import re

import yaml

from pipeline.run import ROOT
from pipeline.sheets import client
from pipeline.tiers import fill_tiers

TAB = "Queue"
HEADER = ["#", "Who", "Tier", "Company", "Role", "Location", "Apply link", "Status", "Score", "Notes", "ID"]
NO_LOGIN_ATS = ("greenhouse", "lever.co", "ashbyhq", "workable", "smartrecruiters", "keka.com", "kula.ai",
                "rippling.com", "applytojob", "greythr", "recruiterflow", "turbohire", "paylocity")
LOGIN_HOSTS = ("myworkdayjobs", "oraclecloud", "ycombinator.com", "wellfound", "equip.co")
TIER_RANK = {"Strong": 0, "Medium": 1, "Exploratory": 2}
WHO_RANK = {"Claude · fill": 0, "Yashvi · login": 1, "Yashvi · Instahyre": 2, "Yashvi · Cutshort": 2,
            "Claude · verify+fill": 3, "Decide": 4}


def who(row: dict, login_companies: set[str]) -> tuple[str, str]:
    """Return (who applies, best apply link) for one Openings row."""
    note, src, url = str(row.get("Notes", "")), row.get("Source", ""), row.get("URL", "")
    found = re.search(r"https?://\S+", note)
    link = found.group(0) if found else url
    if src == "instahyre":
        return "Yashvi · Instahyre", url
    if src == "cutshort":
        return "Yashvi · Cutshort", url
    if row.get("Company") in login_companies or note.startswith("Login") or any(h in link for h in LOGIN_HOSTS):
        return "Yashvi · login", link
    if re.search(r"unverified|likely closed|not found|no company|no careers", note, re.I):
        return "Decide", link
    if any(a in link for a in NO_LOGIN_ATS):
        return "Claude · fill", link
    return "Claude · verify+fill", link


def build(rows: list[dict], login_companies: set[str]) -> list[list]:
    pending = [(*who(r, login_companies), r) for r in rows if r.get("Status") in ("New", "In Progress")]
    pending.sort(key=lambda x: (TIER_RANK.get(x[2].get("Tier", ""), 3), WHO_RANK[x[0]], -int(x[2].get("Score") or 0)))
    return [HEADER] + [
        [i, w, r.get("Tier") or "Untiered", r["Company"], r["Role"], r.get("Location", ""), link,
         r["Status"], r.get("Score", ""), str(r.get("Notes", ""))[:120], r["ID"]]
        for i, (w, link, r) in enumerate(pending, 1)
    ]


def _letter(i: int) -> str:
    return chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26)


def main():
    cfg = yaml.safe_load((ROOT / "config/sheet.yaml").read_text())
    sh = client().open_by_key(os.environ.get("SHEET_ID") or cfg["spreadsheet_id"])
    openings = sh.worksheet("Openings")
    rows = openings.get_all_records(numericise_ignore=["all"])  # keep IDs like "5999548e10" as text
    tiers = fill_tiers(rows)
    if tiers:
        header = openings.row_values(1)
        if "Tier" not in header:
            header.append("Tier")
            openings.update_cell(1, len(header), "Tier")
        col = {c: _letter(header.index(c)) for c in ("Tier", "Status", "Notes")}
        updates = []
        for n, r in enumerate(rows, start=2):
            tier = tiers.get(r.get("ID"))
            if not tier:
                continue
            if tier == "Skip":  # outside the role scope: a hard-no function
                updates += [{"range": f"{col['Status']}{n}", "values": [["Skip"]]},
                            {"range": f"{col['Notes']}{n}", "values": [[f"Skip (auto): hard-no function, {r.get('Location', '')}"]]}]
                r["Status"] = "Skip"
            else:
                updates.append({"range": f"{col['Tier']}{n}", "values": [[tier]]})
                r["Tier"] = tier
        openings.batch_update(updates)
        print(f"Auto-tiered {len(tiers)} new openings ({sum(t == 'Skip' for t in tiers.values())} skipped as hard-no functions)")
    values = build(rows, set(cfg.get("login_companies", [])))
    try:
        ws = sh.worksheet(TAB)
        ws.clear()
    except Exception:  # gspread.WorksheetNotFound — import-free so tests needn't install gspread
        ws = sh.add_worksheet(TAB, rows=len(values) + 50, cols=len(HEADER))
    if ws.row_count < len(values) + 10:
        ws.resize(rows=len(values) + 50)
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    ws.format("A1:K1", {"textFormat": {"bold": True}})
    ws.freeze(rows=1)
    print(f"Queue rebuilt: {len(values) - 1} pending openings")


if __name__ == "__main__":
    main()
