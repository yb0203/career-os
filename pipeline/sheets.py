"""Two-way sync of output/jobs.csv into the Google Sheet's "Openings" tab.

    python -m pipeline.sheets

The sync owns the job columns (priority, score, company, ...). You own Status, Notes and
any column you add yourself: they are read back and preserved on every run. Rows are keyed
by a stable job ID; jobs missing from today's run stay in the sheet with Open = "No".

Auth: GOOGLE_SERVICE_ACCOUNT_JSON (GitHub Actions secret), else your local gcloud login.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
from datetime import date, datetime, timedelta, timezone

import yaml

from pipeline.run import ATS, OUT, ROOT

TAB, SUMMARY_TAB = "Openings", "Summary"
COLUMNS = ["Priority", "Score", "Company", "Role", "Status", "Notes", "Lane", "Location",
           "Posted", "Source", "Apply via", "Why", "Open", "First seen", "Last seen", "URL", "ID"]
TEXT_COLUMNS = {"ID", "Posted", "First seen", "Last seen"}
STATUSES = ["New", "In Progress", "Applied", "Interviewing", "Offer", "Rejected", "Skip"]
LANES = {"growth_strategy": "Growth & Strategy", "ai_pm": "AI PM / TPM", "fractional": "Fractional"}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}
PRUNE_AFTER_DAYS = 30  # untouched ("New") rows gone this long are removed


def client():
    import gspread
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return gspread.service_account_from_dict(json.loads(raw))
    from google.oauth2.credentials import Credentials
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    return gspread.authorize(Credentials(token))


def safe(value) -> str:
    """Scraped text must never be evaluated as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def merge(existing: list[dict], jobs: list[dict], today: str, scanned: set[str] | None = None) -> list[dict]:
    """Pure merge: update known IDs, add new ones, flag vanished ones. Keeps user columns.

    `scanned` = sources that answered this run ("ats" covers every watchlist board). Rows from any
    other source (rate-limited, disabled, or added by hand) keep their Open value instead of being
    flagged as gone. None = old behaviour: every missing row is flagged.
    """
    by_id = {r["ID"]: r for r in existing if r.get("ID")}
    seen = set()
    for j in jobs:
        row = by_id.setdefault(j["id"], {"Status": "New", "Notes": "", "First seen": today})
        row.update({
            "ID": j["id"], "Priority": j["priority"], "Score": j["score"], "Company": j["company"],
            "Role": j["title"], "Lane": LANES.get(j["lane"], j["lane"]), "Location": j["location"],
            "Posted": j["posted_at"] or "?", "Source": j["source"].split(":")[0],
            "Apply via": j.get("apply_via") or "", "Why": j["reasons"],
            "URL": j["url"], "Open": "Yes", "Last seen": today,
        })
        seen.add(j["id"])

    cutoff = (date.fromisoformat(today) - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    rows = []
    for rid, row in by_id.items():
        src = row.get("Source", "")
        src = "ats" if src in ATS else src
        if rid not in seen and (scanned is None or src in scanned):
            row["Open"] = "No"
            if row.get("Status", "New") in ("New", "") and row.get("Last seen", today) < cutoff:
                continue
        rows.append(row)
    rows.sort(key=lambda r: (r.get("Open") != "Yes", PRIORITY_ORDER.get(r.get("Priority"), 9),
                             -int(r.get("Score") or 0)))
    return rows


def read_rows(ws) -> tuple[list[str], list[dict]]:
    values = ws.get_all_values()
    if not values:
        return COLUMNS, []
    header = values[0]
    return header, [dict(zip(header, r)) for r in values[1:] if any(r)]


def to_values(header: list[str], rows: list[dict]) -> list[list]:
    out = [header]
    for r in rows:
        line = []
        for col in header:
            if col == "Role" and r.get("URL"):
                title = str(r.get("Role", "")).replace('"', "'")
                line.append(f'=HYPERLINK("{r["URL"]}", "{title}")')
            elif col == "Score":
                line.append(int(r.get("Score") or 0))
            elif col in TEXT_COLUMNS and r.get(col):
                line.append("'" + str(r[col]))  # keep IDs like "12e4…" and ISO dates as text
            else:
                line.append(safe(r.get(col, "")))
        out.append(line)
    return out


def migration_requests(sheet_id: int, old_header: list[str]) -> list[dict]:
    """Insert real sheet columns for managed fields this sheet doesn't have yet.

    Inserting (rather than just rewriting values one column over) lets Google Sheets shift the
    existing filter, conditional formats, widths and the user's own columns along with the data.
    """
    if not any(old_header):
        return []  # empty sheet: the first-run setup lays everything out
    cur, reqs = list(old_header), []
    for i, name in enumerate(COLUMNS):
        if name in cur:
            continue
        prev = COLUMNS[i - 1] if i else None
        pos = cur.index(prev) + 1 if prev in cur else len(cur)
        reqs.append({"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                                   "startIndex": pos, "endIndex": pos + 1},
                                         "inheritFromBefore": pos > 0}})
        cur.insert(pos, name)
    return reqs


def format_requests(sheet_id: int, n_rows: int, header: list[str], first_run: bool) -> list[dict]:
    col = header.index
    rng = lambda c, start=1: {"sheetId": sheet_id, "startRowIndex": start, "endRowIndex": max(n_rows, 2),
                              "startColumnIndex": c, "endColumnIndex": c + 1}
    reqs = [
        {"setDataValidation": {"range": rng(col("Status")), "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUSES]},
            "showCustomUi": True, "strict": False}}},
    ]
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
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 4}},
                                   "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
    ]
    for text, bg in (("P0", color(0.72, 0.88, 0.75)), ("P1", color(1, 0.95, 0.75))):
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(col("Priority"))],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": text}]},
                            "format": {"backgroundColor": bg}}}}})
    open_letter = chr(ord("A") + col("Open"))
    reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(header)}],
        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f'=${open_letter}2="No"'}]},
                        "format": {"textFormat": {"foregroundColor": color(0.6, 0.6, 0.6)}}}}}})
    widths = {"Priority": 60, "Score": 55, "Company": 170, "Role": 320, "Status": 110, "Notes": 220,
              "Lane": 130, "Location": 200, "Apply via": 110, "Why": 260, "URL": 120, "ID": 90}
    for name, px in widths.items():
        if name in header:
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col(name), "endIndex": col(name) + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    return reqs


def summary_values(header: list[str], synced_at: str) -> list[list]:
    letter = lambda name: chr(ord("A") + header.index(name))
    o, p, s, l, src = (f"{TAB}!{letter(c)}:{letter(c)}" for c in ("Open", "Priority", "Status", "Lane", "Source"))
    rows = [["career-os · Job Openings", ""], ["Last synced", synced_at], ["", ""],
            ["Open roles by priority", "Count"]]
    rows += [[k, f'=COUNTIFS({o},"Yes",{p},"{k}")'] for k in ("P0", "P1", "P2")]
    rows += [["", ""], ["My pipeline (all rows)", "Count"]]
    rows += [[st, f'=COUNTIF({s},"{st}")'] for st in STATUSES]
    rows += [["", ""], ["Open roles by lane", "Count"]]
    rows += [[v, f'=COUNTIFS({o},"Yes",{l},"{v}")'] for v in LANES.values()]
    rows += [["", ""], ["Open roles by source", "Count"],
             [f'=QUERY({TAB}!A:{letter("ID")},"select {letter("Source")}, count({letter("ID")}) where {letter("Open")} = \'Yes\' group by {letter("Source")} order by count({letter("ID")}) desc label count({letter("ID")}) \'\'",1)', ""]]
    return rows


def sync(spreadsheet_id: str) -> int:
    with (OUT / "jobs.csv").open() as fh:
        jobs = list(csv.DictReader(fh))
    sh = client().open_by_key(spreadsheet_id)
    ws = sh.worksheet(TAB)
    header, existing = read_rows(ws)
    migrate = migration_requests(ws.id, header)
    if migrate:
        sh.batch_update({"requests": migrate})
        ws = sh.worksheet(TAB)  # refresh cached column count before any resize
    meta =sh.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,conditionalFormats)"})
    first_run = not any(s.get("conditionalFormats") for s in meta["sheets"]
                        if s["properties"]["sheetId"] == ws.id)
    # Keep any column the user added, after the managed ones
    header = COLUMNS + [h for h in header if h and h not in COLUMNS]

    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
    meta = OUT / "run_meta.json"
    scanned = set(json.loads(meta.read_text())["scanned"]) if meta.exists() else None
    rows = merge(existing, jobs, now.date().isoformat(), scanned)
    values = to_values(header, rows)

    ws.clear()
    if ws.row_count < len(values) + 50 or ws.col_count < len(header):
        ws.resize(rows=len(values) + 200, cols=max(len(header), ws.col_count))
    ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
    sh.batch_update({"requests": format_requests(ws.id, len(values), header, first_run)})

    summary = sh.worksheet(SUMMARY_TAB)
    summary.clear()
    summary.update(values=summary_values(header, now.strftime("%d %b %Y, %H:%M IST")),
                   range_name="A1", value_input_option="USER_ENTERED")
    if first_run:
        summary.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
        summary.format("A4:B4", {"textFormat": {"bold": True}})

    open_rows = sum(r.get("Open") == "Yes" for r in rows)
    print(f"Synced {len(rows)} rows ({open_rows} open, {len(rows) - open_rows} no longer listed) "
          f"to https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    return len(rows)


def main():
    cfg = yaml.safe_load((ROOT / "config/sheet.yaml").read_text())
    sync(os.environ.get("SHEET_ID") or cfg["spreadsheet_id"])


if __name__ == "__main__":
    main()
