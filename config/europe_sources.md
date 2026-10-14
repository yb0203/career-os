# Europe search: where roles come from

Checked 2026-10-15. "Used" sources run in the daily job (`python -m pipeline.europe_sheet`). Nothing here logs in, creates accounts or bypasses a bot check.

## Used (automatic, daily)
| Source | How | Notes |
|---|---|---|
| Arbeitnow | Public JSON API, `visa_sponsorship=true` filter, up to 4 pages on .com and the .co.uk/.nl/.ch/.fr boards | Free API ("please do not abuse"), 1.5 s between pages. Every hit counts as a sponsorship signal unless the text says otherwise. Link is Arbeitnow's page, so apply method = Aggregator |
| Relocate.me | Server-rendered HTML, `/international-jobs`, up to 6 pages | robots.txt allows it; no scraping clause found in its terms/privacy page. Every listing is relocation-supported by design. Applying needs their Google/LinkedIn connect, so Aggregator |
| Berlin Startup Jobs | Public RSS feed (`/engineering/feed/`, ~12 items) | Feed offered for syndication; rarely carries a visa phrase |
| Remotive, RemoteOK, Himalayas, Jobicy, We Work Remotely, Working Nomads | Existing `pipeline/sources/remote_boards.py` functions | Kept only if remote AND location says worldwide or EU/EMEA/Europe and no US-only wording |
| Company ATS watchlist (`watchlist` in `europe.yaml`, ~145 employers) | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Personio, Teamtailor, Recruitee public career-page feeds | All slugs answered with jobs on 2026-10-15. Re-verify with `python -m pipeline.europe --check`. Workable throttles (HTTP 429) after bursts; the daily run makes only two Workable calls and tolerates a miss |

## Manual, weekly (open in a browser; not fetched)
| Site | Why not automated |
|---|---|
| Landing.jobs (https://landing.jobs/jobs) | robots.txt disallows `/api/` and `/jobs/search`; the listing is a JS search. Good for Portugal/Europe relocation |
| NoFluffJobs (https://nofluffjobs.com) | robots.txt disallows `/api/`; search is JS-driven |
| WeAreDevelopers (https://www.wearedevelopers.com/jobs) | JS app on a private API; its robots signals opt out of AI training use. Mostly German-language local roles; no visa filter |
| LinkedIn / Indeed / Glassdoor | Login or bot checks. Use the "visa sponsorship" keyword with Europe filters by hand |
| Wellfound | Terms discourage scraping (already off in `config/sources.yaml`) |
| Own career pages with no public ATS feed | Klarna, Zalando, Booking.com, Revolut, Vinted, Bolt, Mistral AI (Lever board is empty), Hugging Face (Workable, throttled when probed). Check by hand |

## Login needed
- SwissDevJobs and GermanTechJobs (same operator): the sites now redirect to a JobCopilot sign-up page.
- Relocate.me "Apply" (Google/LinkedIn connect) and Workday/Oracle/iCIMS company portals: marked `Account needed` or `Aggregator` in the sheet so direct ones rank higher.

## Blocked
- jobbland.se: HTTP 403 to non-browser clients.

## Dead (unreachable on 2026-10-15)
- eu-tech-jobs.com, jobbland.com, jobs.eu-startups.com, techjobs.se, eutechjobs.com (connection failed). eurotechjobs.com serves only a "page not found" shell.

## Coverage gap to know about
Most Nordic employers (Spotify, Wolt, Supercell, Epidemic Sound, Lovable and others) do hire from abroad but rarely write visa or relocation wording into each posting, so they do not appear unless a posting says so or is remote EU/EMEA. Pleo explicitly says it cannot sponsor for some roles, while Supercell's careers page advertises relocation help in general (check its roles by hand). To widen the Nordic list, check their careers FAQ pages by hand and add a note in the sheet's Notes column.
