"""Laptop-side refresh (2026-10-29), run by launchd at 07:05 and 19:05 IST (com.yashvi.careeros.refresh).

GitHub's runners are throttled by LinkedIn (about 26 postings vs about 150 from this laptop) and start scheduled runs
3-6 hours late, so this fetches the throttle-prone sources locally and then syncs the sheet. It is safe next to
the cloud run: the sheet sync only closes rows of sources that answered (output/run_meta.json "scanned").
Run by hand: .venv/bin/python scripts/refresh_local.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SOURCES = ["linkedin", "weekday", "instahyre", "cutshort", "unstop", "remoterocketship", "himalayas"]
STEPS = [["-m", "pipeline.run", "--only", *SOURCES], ["-m", "pipeline.sheets"], ["-m", "pipeline.queue"],
         ["-m", "pipeline.pm_targets"], ["-m", "pipeline.daily_batch"]]


def main() -> int:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    print("=== refresh", time.strftime("%F %T"), flush=True)
    code = 0
    for step in STEPS:
        r = subprocess.run([PY, *step], cwd=ROOT, env=env)
        if r.returncode:
            print(f"step failed ({' '.join(step[1:3])}): exit {r.returncode}", flush=True)
            code = r.returncode
            if step[1] == "pipeline.run":   # without fresh data the later steps would only re-sync old data
                break
    subprocess.run(["git", "checkout", "--", "output/"], cwd=ROOT, stderr=subprocess.DEVNULL)  # keep the repo clean
    print("=== done", time.strftime("%F %T"), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
