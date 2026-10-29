#!/bin/bash
# Laptop-side refresh (2026-10-29). GitHub's runners get throttled by LinkedIn (26 postings vs ~150 from here)
# and start 3-6 h late, so this runs the throttle-prone sources from the laptop, then syncs the sheet.
# Safe next to the cloud run: the sync only closes rows of sources that answered (run_meta.json "scanned").
set -u
cd "$HOME/Documents/career-os" || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
echo "=== refresh $(date '+%F %T')"
$PY -m pipeline.run --only linkedin weekday instahyre cutshort unstop remoterocketship himalayas || echo "run failed"
$PY -m pipeline.sheets
$PY -m pipeline.queue
$PY -m pipeline.pm_targets
$PY -m pipeline.daily_batch
git checkout -- output/ 2>/dev/null   # keep the repo clean; the cloud run owns the committed digest
echo "=== done $(date '+%F %T')"
