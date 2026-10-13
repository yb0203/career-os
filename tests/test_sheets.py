from pipeline.sheets import COLUMNS, merge, migration_requests, safe, to_values


def job(i, priority="P0", score=85):
    return {"id": i, "priority": priority, "score": str(score), "company": f"Co{i}", "title": "PM",
            "lane": "ai_pm", "location": "Bangalore", "posted_at": "2026-10-10", "source": "getro:jobs.accel.com",
            "apply_via": "lever", "reasons": "", "url": f"https://x/{i}"}


def test_new_rows_get_status_new_and_first_seen():
    rows = merge([], [job("a")], "2026-10-12")
    assert rows[0]["Status"] == "New" and rows[0]["First seen"] == "2026-10-12"
    assert rows[0]["Lane"] == "AI PM / TPM" and rows[0]["Source"] == "getro"
    assert rows[0]["Apply via"] == "lever"


def test_apply_via_column_sits_right_after_source():
    assert COLUMNS.index("Apply via") == COLUMNS.index("Source") + 1
    values = to_values(COLUMNS, merge([], [job("a")], "2026-10-12"))
    assert dict(zip(COLUMNS, values[1]))["Apply via"] == "lever"


def test_rows_from_older_csv_without_apply_via_still_merge():
    old = job("a")
    old.pop("apply_via")
    assert merge([], [old], "2026-10-12")[0]["Apply via"] == ""


def test_existing_sheet_gets_apply_via_column_inserted_after_source():
    old_header = [c for c in COLUMNS if c != "Apply via"] + ["My column"]
    reqs = migration_requests(7, old_header)
    assert len(reqs) == 1
    rng = reqs[0]["insertDimension"]["range"]
    assert (rng["sheetId"], rng["startIndex"], rng["endIndex"]) == (7, old_header.index("Source") + 1,
                                                                      old_header.index("Source") + 2)
    assert migration_requests(7, COLUMNS + ["My column"]) == []
    assert migration_requests(7, []) == []


def test_user_columns_survive_updates():
    existing = [{"ID": "a", "Status": "Applied", "Notes": "referral from Priya", "First seen": "2026-10-01",
                 "Score": "70", "Priority": "P1", "Open": "Yes", "Last seen": "2026-10-11", "My column": "x"}]
    row = merge(existing, [job("a", score=90)], "2026-10-12")[0]
    assert (row["Status"], row["Notes"], row["My column"]) == ("Applied", "referral from Priya", "x")
    assert row["Apply via"] == "lever"
    header = COLUMNS + ["My column"]
    written = dict(zip(header, to_values(header, [row])[1]))
    assert written["My column"] == "x" and written["Apply via"] == "lever"
    assert row["Score"] == "90" and row["First seen"] == "2026-10-01" and row["Last seen"] == "2026-10-12"


def test_vanished_jobs_flagged_and_stale_untouched_ones_pruned():
    existing = [
        {"ID": "gone-applied", "Status": "Applied", "Last seen": "2026-08-01", "Open": "Yes"},
        {"ID": "gone-new-old", "Status": "New", "Last seen": "2026-08-01", "Open": "Yes"},
        {"ID": "gone-new-recent", "Status": "New", "Last seen": "2026-10-11", "Open": "Yes"},
    ]
    rows = {r["ID"]: r for r in merge(existing, [job("a")], "2026-10-12")}
    assert rows["gone-applied"]["Open"] == "No"      # your tracked rows are never deleted
    assert "gone-new-old" not in rows                 # untouched + gone 30+ days
    assert rows["gone-new-recent"]["Open"] == "No"
    assert next(iter(rows)) == "a"                    # open rows sort first


def test_scraped_text_cannot_become_a_formula():
    assert safe('=IMPORTXML("http://evil")') == '\'=IMPORTXML("http://evil")'
    values = to_values(COLUMNS, merge([], [dict(job("a"), company="=HACK()")], "2026-10-12"))
    row = dict(zip(COLUMNS, values[1]))
    assert row["Company"].startswith("'=")
    assert row["Role"].startswith('=HYPERLINK("https://x/a"')


def test_ids_and_dates_written_as_text():
    values = to_values(COLUMNS, merge([], [job("12e4567890")], "2026-10-12"))
    row = dict(zip(COLUMNS, values[1]))
    assert row["ID"] == "'12e4567890" and row["First seen"] == "'2026-10-12"
