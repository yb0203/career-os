# career-os

**I got tired of applying to job links that turned out to be dead, so I built my own sourcing engine.**

Every morning, `career-os` pulls open roles from **14 sources**: the hiring systems (ATS) of ~90 target companies, LinkedIn, India startup boards, remote-job boards, Hacker News and 14 VC portfolio job boards. It throws out anything stale, out of reach, off-target or already closed, merges duplicates, scores what's left against the lanes I'm hiring for, and commits a ranked digest to [`output/digest.md`](output/digest.md).

> Live run, 12 Oct 2026: **15,407 postings → 292 roles that pass every gate → 22 to apply to today**, in about 80 seconds.

## Why this exists

Aggregators and job-SEO pages repost listings long after they close. In one sourcing pass, most "open" roles I found returned 404s. The fix is to go to the origin:

| Problem | What career-os does |
|---|---|
| Dead / reposted listings | Reads the company's own Greenhouse, Lever or Ashby board API, so every posting is live |
| "Remote" that means US-only | Location gate rejects region-locked remote roles |
| Roles that want 8+ years | Experience gate parses "N+ years" from the JD |
| Noise from unrelated functions | Title allowlist per lane + exclusion list |
| Too many to triage | 0–100 fit score → P0 / P1 / P2 |

## Sources

| Tier | Source | How | Coverage |
|---|---|---|---|
| 1 | **Company ATS boards**: Greenhouse, Lever, Ashby ([`watchlist.yaml`](watchlist.yaml)) | Public board APIs | ~90 AI, fintech & SaaS companies; always live, with full JDs |
| 2 | **LinkedIn** | Public guest job search, past 7 days | Bengaluru + India |
| 2 | **Instahyre**, **Cutshort** | Public search APIs / pages | India startups, PM & ops |
| 2 | **VC portfolio boards**: Getro (Accel, Blume, 3one4, Antler, General Catalyst, Insight, Thrive) and Consider (Peak XV, Lightspeed, Sequoia, Kleiner Perkins, First Round, GV, Bessemer) | Board search APIs | Thousands of portfolio-startup roles |
| 2 | **Y Combinator** Work at a Startup | Public listing pages | YC startups: product, ops, India, remote |
| 2 | **Remote boards**: We Work Remotely, Remotive, RemoteOK, Himalayas, Jobicy, Working Nomads | Public APIs / RSS | Worldwide-remote roles |
| 3 | **Hacker News** "Who is hiring?" | Algolia HN API | Latest monthly thread |

Switch sources on or off in [`config/sources.yaml`](config/sources.yaml). Anything not read straight from an ATS gets a **live-link check** before it reaches the digest, and the same role found in several places is merged into one row.

## How it works

```
watchlist.yaml + config/sources.yaml ──► 14 sources in parallel
                        │  ~15k postings
                        ▼
                  gates.py   lane title · ≤14 days · location · ≤5 yrs
                        │
                        ▼
                  dedupe → live-link check (non-ATS) → scorer.py
                        │  lane 35 · exact title 5 · location 20 · freshness 15 · seniority 15 · keywords 10
                        ▼
          output/jobs.csv  +  output/digest.md   (committed daily by GitHub Actions)
                        │
                        ▼
          Google Sheet "Openings" tab (two-way sync) + "Summary" tab
```

### Google Sheet sync

`python -m pipeline.sheets` upserts every kept role into a private Google Sheet, keyed by a stable job ID (company + title).

- **The sync owns** Priority, Score, Company, Role (linked), Lane, Location, Posted, Source, Apply via (Lever / Greenhouse / Ashby, or the posting site), Why, Open, First/Last seen.
- **I own** `Status` (New → Shortlisted → Applied → Interviewing → Offer / Rejected / Skip), `Notes`, and any column I add. These are read back and preserved on every run.
- Roles that drop out of the feed stay with `Open = No`, never deleted, unless untouched (`New`) for 30 days.
- Scraped text is escaped so it can never run as a sheet formula.
- Runs daily in GitHub Actions with a service-account key (`GOOGLE_SERVICE_ACCOUNT_JSON` secret), or locally with your `gcloud` login.

**P0 = apply today**: fresh, reachable location, target title. Roles with no post date (Instahyre, Cutshort, YC) are capped at P1 until verified.

**Lanes** (edit in [`config/lanes.yaml`](config/lanes.yaml)):
- **Growth & Strategy**: Founder's Office, Chief of Staff, BizOps, Strategy & Ops, GTM, Deployment Strategist
- **AI PM / TPM**: Product Manager, Technical Program Manager, Solutions Engineer, Forward Deployed
- **Fractional / Contract**: any of the above, on contract or part-time

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.run                      # all sources
python -m pipeline.run --only linkedin yc   # just these ("ats" = company watchlist)
python -m pipeline.run --company Zeta       # one watchlist company
python -m pipeline.probe razorpay      # which ATS does a company use?
python -m pytest -q
```

## Repo map

```
career-os/
├── pipeline/          # fetchers/ (ATS), sources/ (boards), gates.py, scorer.py, run.py, probe.py
├── config/
│   ├── lanes.yaml     # lanes, gates and scoring weights
│   └── sources.yaml   # which boards to search, and with what terms
├── watchlist.yaml     # target companies + verified ATS slugs
├── output/            # daily digest (generated)
├── applications/      # per-role kits: tailored resume notes, pitch, demo link
├── resumes/           # base resume variants per lane
├── projects/          # Streamlit mini-projects, each deployable on its own
└── .github/workflows/daily.yml
```

## Roadmap

- [ ] Grow the ATS watchlist toward 150, with more India-based and remote-India startups
- [ ] Founder hiring posts on LinkedIn/X (≤3 days old)
- [ ] Wellfound and Naukri (both block simple automated access today)
- [ ] Sync to Google Sheets + daily email digest
- [ ] Mini-projects in `projects/`, each with a live Streamlit demo

Built by [Yashvi Bansal](https://yb0203.github.io/), Technical Platform Owner at Kotak Mahindra Bank · IIT BHU.
