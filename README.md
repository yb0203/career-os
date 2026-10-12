# career-os

**I got tired of applying to job links that turned out to be dead, so I built my own sourcing engine.**

Every morning, `career-os` pulls every open role straight from the hiring systems (ATS) of ~90 target companies. It throws out anything stale, out of reach, or off-target, scores what's left against the lanes I'm hiring for, and commits a ranked digest to [`output/digest.md`](output/digest.md).

> First live run: **8,274 postings → 7 roles worth applying to** — in under 10 seconds.

## Why this exists

Aggregators and job-SEO pages repost listings long after they close. In one sourcing pass, most "open" roles I found returned 404s. The fix is to go to the origin:

| Problem | What career-os does |
|---|---|
| Dead / reposted listings | Reads the company's own Greenhouse, Lever or Ashby board API, so every posting is live |
| "Remote" that means US-only | Location gate rejects region-locked remote roles |
| Roles that want 8+ years | Experience gate parses "N+ years" from the JD |
| Noise from unrelated functions | Title allowlist per lane + exclusion list |
| Too many to triage | 0–100 fit score → P0 / P1 / P2 |

## How it works

```
watchlist.yaml ──► fetchers (Greenhouse · Lever · Ashby)
                        │  ~8k live postings
                        ▼
                  gates.py   lane title · ≤14 days · location · ≤5 yrs
                        │
                        ▼
                  scorer.py  lane 40 · location 20 · freshness 15 · seniority 15 · keywords 10
                        │
                        ▼
          output/jobs.csv  +  output/digest.md   (committed daily by GitHub Actions)
```

**Lanes** (edit in [`config/lanes.yaml`](config/lanes.yaml)):
- **Growth & Strategy**: Founder's Office, Chief of Staff, BizOps, Strategy & Ops, GTM, Deployment Strategist
- **AI PM / TPM**: Product Manager, Technical Program Manager, Solutions Engineer, Forward Deployed
- **Fractional / Contract**: any of the above, on contract or part-time

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.run                 # full watchlist
python -m pipeline.run --company Zeta  # one company
python -m pipeline.probe razorpay      # which ATS does a company use?
python -m pytest -q
```

## Repo map

```
career-os/
├── pipeline/          # fetchers/, gates.py, scorer.py, run.py, probe.py
├── config/lanes.yaml  # lanes, gates and scoring weights
├── watchlist.yaml     # target companies + verified ATS slugs
├── output/            # daily digest (generated)
├── applications/      # per-role kits: tailored resume notes, pitch, demo link
├── resumes/           # base resume variants per lane
├── projects/          # Streamlit mini-projects, each deployable on its own
└── .github/workflows/daily.yml
```

## Roadmap

- [ ] Grow the watchlist toward 150, with more India-based and remote-India startups
- [ ] Tier 2 sources: YC Work at a Startup, Wellfound, VC portfolio job boards
- [ ] Tier 3: founder hiring posts on LinkedIn/X (≤3 days old)
- [ ] Sync to Google Sheets + daily email digest
- [ ] Mini-projects in `projects/`, each with a live Streamlit demo

Built by [Yashvi Bansal](https://yb0203.github.io/), Technical Platform Owner at Kotak Mahindra Bank · IIT BHU.
