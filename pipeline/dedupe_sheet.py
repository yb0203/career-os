"""Mark duplicate jobs in the sheet so counts are true.   python -m pipeline.dedupe_sheet

Runs after every sync (daily.yml). Extra copies of the same company+role (different source, spelling or suffix) become
Status Skip with "Duplicate of ..." in Notes; the keeper row is never touched. See pipeline/dedupe.py.
"""
from __future__ import annotations

import os

import yaml

from pipeline.dedupe import plan_updates
from pipeline.queue import _letter
from pipeline.run import ROOT
from pipeline.sheets import client


def main():
    cfg = yaml.safe_load((ROOT / "config/sheet.yaml").read_text())
    sh = client().open_by_key(os.environ.get("SHEET_ID") or cfg["spreadsheet_id"])
    total = 0
    for tab in ("Openings", "Europe"):
        ws = sh.worksheet(tab)
        header = ws.row_values(1)
        rows = ws.get_all_records(numericise_ignore=["all"])
        plan = plan_updates(rows)
        if not plan:
            continue
        sc, nc = _letter(header.index("Status")), _letter(header.index("Notes"))
        updates = []
        for n, r in enumerate(rows, start=2):
            if r.get("ID") in plan:
                status, note = plan[r["ID"]]
                updates += [{"range": f"{sc}{n}", "values": [[status]]}, {"range": f"{nc}{n}", "values": [[note]]}]
        ws.batch_update(updates)
        total += len(plan)
        print(f"{tab}: marked {len(plan)} duplicate rows as Skip")
    print(f"Duplicates marked: {total}")


if __name__ == "__main__":
    main()
