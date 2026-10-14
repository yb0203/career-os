"""Write the Europe search to its own "Europe" tab in the career-os Google Sheet.

    python -m pipeline.europe_sheet

The run owns the job columns. You own Status, Notes and any column you add yourself: they are
read back and preserved. Rows are keyed by the stable job ID; roles that vanish stay in the sheet
with Open = "No" when you have touched them (any Status other than New) and are dropped otherwise.

Auth: GOOGLE_SERVICE_ACCOUNT_JSON (GitHub Actions secret), else your local gcloud login.
"""
from __future__ import annotations

import collections
import os
from datetime import date, datetime, timedelta, timezone

import yaml

from pipeline.europe import fetch_all
from pipeline.europe_ats import ATS_FETCHERS
from pipeline.run import ROOT
from pipeline.sheets import STATUSES, client, safe  # reused as-is, not modified

TAB = "Europe"
COLUMNS = ["Score", "Company", "Role", "Family", "AI", "Country", "Nordic", "Visa/Relocation", "Remote",
           "Apply method", "Apply link", "Status", "Notes", "Why", "Posted", "First seen", "Last seen",
           "Open", "Source", "ID"]
TEXT_COLUMNS = {"ID", "Posted", "First seen", "Last seen"}
PRUNE_AFTER_DAYS = 7  # untouched ("New") rows gone this long are removed
REMOTE_BOARDS = {"remotive", "remoteok", "himalayas", "jobicy", "weworkremotely", "workingnomads"}
APPLY_ORDER = {"Direct (no login)": 0, "Account needed": 1, "Aggregator": 2}


def source_group(name: str) -> str:
    """Map a row's Source part to the group fetch_all() reports as scanned."""
    if name in ATS_FETCHERS:
        return "ats"
    return "remote-boards" if name in REMOTE_BOARDS else name


def merge(existing: list[dict], fresh: list[dict], today: str, scanned: set[str] | None = None) -> list[dict]:
    """Pure merge: update known IDs, add new ones, flag vanished ones. Keeps Status, Notes, user columns.

    `scanned` = source groups that answered this run. A row whose sources were not all scanned keeps
    its Open value (a rate-limited source must not make its roles look closed). None = all scanned.
    """
    by_id = {r["ID"]: dict(r) for r in existing if r.get("ID")}
    seen = set()
    for j in fresh:
        row = by_id.setdefault(j["ID"], {"Status": "New", "Notes": "", "First seen": today})
        row.update({c: j.get(c, "") for c in COLUMNS if c not in ("Status", "Notes", "First seen", "Last seen", "Open")})
        row.update({"Open": "Yes", "Last seen": today})
        seen.add(j["ID"])

    cutoff = (date.fromisoformat(today) - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    rows = []
    for rid, row in by_id.items():
        if rid not in seen:
            parts = [p for p in str(row.get("Source", "")).split("+") if p]
            all_scanned = scanned is None or (parts and all(source_group(p) in scanned for p in parts))
            if all_scanned:
                row["Open"] = "No"
                if row.get("Status", "New") in ("New", "") and row.get("Last seen", today) < cutoff:
                    continue
        rows.append(row)
    rows.sort(key=lambda r: (r.get("Open") != "Yes", -int(float(r.get("Score") or 0)), r.get("Company", "")))
    return rows


def to_values(header: list[str], rows: list[dict]) -> list[list]:
    out = [header]
    for r in rows:
        line = []
        for col in header:
            if col == "Score":
                line.append(int(float(r.get("Score") or 0)))
            elif col in TEXT_COLUMNS and r.get(col):
                line.append("'" + str(r[col]))  # keep IDs like "12e4..." and ISO dates as text
            else:
                line.append(safe(r.get(col, "")))
        out.append(line)
    return out


def read_rows(ws) -> tuple[list[str], list[dict]]:
    values = ws.get_all_values()
    if not values or not any(values[0]):
        return [], []
    header = values[0]
    try:
        records = ws.get_all_records(numericise_ignore=["all"])
    except Exception:  # blank/duplicate header cells (a column you added): fall back to a plain zip
        records = [dict(zip(header, r)) for r in values[1:]]
    return header, [r for r in records if any(str(v).strip() for v in r.values())]


def format_requests(sheet_id: int, n_rows: int, header: list[str], first_run: bool) -> list[dict]:
    col = header.index
    rng = lambda c: {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": max(n_rows, 2),
                     "startColumnIndex": c, "endColumnIndex": c + 1}
    reqs = [{"setDataValidation": {"range": rng(col("Status")), "rule": {
        "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUSES]},
        "showCustomUi": True, "strict": False}}}]
    if not first_run:
        return reqs  # leave the user's filters, colours and widths alone after setup
    color = lambda r, g, b: {"red": r, "green": g, "blue": b}
    reqs += [
        {"setBasicFilter": {"filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0,
                                                 "startColumnIndex": 0, "endColumnIndex": len(header)}}}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "foregroundColor": color(1, 1, 1)},
                                                       "backgroundColor": color(0.18, 0.2, 0.25)}},
                        "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 3}},
                                   "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
    ]
    for name, text, bg in (("Nordic", "Yes", color(0.72, 0.88, 0.75)), ("Apply method", "Direct (no login)", color(0.85, 0.93, 1))):
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(col(name))],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": text}]},
                            "format": {"backgroundColor": bg}}}}})
    open_letter = chr(ord("A") + col("Open"))
    reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(header)}],
        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f'=${open_letter}2="No"'}]},
                        "format": {"textFormat": {"foregroundColor": color(0.6, 0.6, 0.6)}}}}}})
    widths = {"Score": 55, "Company": 160, "Role": 320, "Family": 90, "AI": 45, "Country": 170, "Nordic": 60,
              "Visa/Relocation": 120, "Remote": 70, "Apply method": 130, "Apply link": 120, "Status": 110,
              "Notes": 220, "Why": 380, "Source": 110, "ID": 90}
    for name, px in widths.items():
        if name in header:
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col(name), "endIndex": col(name) + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    return reqs


def summarize(rows: list[dict]) -> str:
    open_rows = [r for r in rows if r.get("Open") == "Yes"]
    by_country: collections.Counter = collections.Counter()
    nordic_names = {"Sweden", "Norway", "Denmark", "Finland", "Iceland"}
    for r in open_rows:
        for c in str(r["Country"]).split(" / "):
            by_country[c] += 1
    lines = [f"{len(open_rows)} open qualifying roles ({len(rows) - len(open_rows)} no longer listed)", "By country (a multi-country role counts in each):"]
    nordics = [(c, n) for c, n in by_country.most_common() if c in nordic_names]
    lines.append("  NORDICS: " + (", ".join(f"{c} {n}" for c, n in nordics) or "none") +
                 f"  (roles with a Nordic location: {sum(r['Nordic'] == 'Yes' for r in open_rows)})")
    lines.append("  Other: " + ", ".join(f"{c} {n}" for c, n in by_country.most_common() if c not in nordic_names))
    lines.append("By family: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(r["Family"] for r in open_rows).most_common()))
    lines.append("By apply method: " + ", ".join(f"{k} {v}" for k, v in sorted(
        collections.Counter(r["Apply method"] for r in open_rows).items(), key=lambda kv: APPLY_ORDER.get(kv[0], 9))))
    lines.append("By visa signal: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(r["Visa/Relocation"] for r in open_rows).most_common()))
    return "\n".join(lines)


def sync(spreadsheet_id: str) -> list[dict]:
    fresh, scanned, stats = fetch_all()
    if stats["errors"]:
        print("source errors:", "; ".join(stats["errors"]))
    sh = client().open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(TAB)
        created = False
    except Exception:  # gspread.WorksheetNotFound
        ws = sh.add_worksheet(TAB, rows=max(len(fresh) + 200, 500), cols=len(COLUMNS) + 2)
        created = True
    header, existing = read_rows(ws)
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,conditionalFormats)"})
    first_run = created or not any(s.get("conditionalFormats") for s in meta["sheets"]
                                   if s["properties"]["sheetId"] == ws.id)
    header = COLUMNS + [h for h in header if h and h not in COLUMNS]  # keep columns you added

    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
    if not scanned:  # every source failed: change nothing rather than flag the whole sheet closed
        print("No source answered; leaving the Europe tab untouched.")
        return existing
    rows = merge(existing, fresh, now.date().isoformat(), scanned)
    values = to_values(header, rows)

    ws.clear()
    if ws.row_count < len(values) + 50 or ws.col_count < len(header):
        ws.resize(rows=len(values) + 200, cols=max(len(header), ws.col_count))
    ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
    sh.batch_update({"requests": format_requests(ws.id, len(values), header, first_run)})
    print(f"Wrote {len(rows)} rows to the '{TAB}' tab of https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    print(summarize(rows))
    return rows


def main():
    cfg = yaml.safe_load((ROOT / "config/sheet.yaml").read_text())
    sync(os.environ.get("SHEET_ID") or cfg["spreadsheet_id"])


if __name__ == "__main__":
    main()
