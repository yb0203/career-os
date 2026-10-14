# Remote job boards: coverage check

The 30 boards from a LinkedIn "remote job boards" post, probed on 2026-10-14.
Status key: **source** = already pulled by the pipeline; **manual** = no easy public feed, check weekly; **skip** = dead, blocked or off-target.

| Board | Status | Note |
|---|---|---|
| remotive.io | source | `remotive` |
| remotehunt.com | source | Redirects to weworkremotely (`weworkremotely`) |
| themuse.com | source | `themuse`: public API, Product Management, Remote + Bangalore |
| powertofly.com | manual: check weekly | Page loads, but no JSON-LD job data or open API found |
| idealist.org | manual: check weekly | Mostly non-profit roles; JS app, no public feed found |
| dynamitejobs.co | manual: check weekly | Now dynamitejobs.com; listings have no JSON or JSON-LD, sitemap has no jobs |
| crossover.com | manual: check weekly | Single-pipeline hiring, not individual postings; sitemap has only blog pages |
| remoters.net | manual: check weekly | Reachable with a browser UA; WordPress listings, no jobs REST endpoint, few PM roles |
| remotewoman.com | skip | Feeds contain blog posts, not jobs |
| remotehub.io | skip | Feeds contain blog posts, not jobs |
| remoteworkhub.com | skip | Feeds contain blog posts, not jobs |
| jobmote.com | skip | Redirects to scrums.com (dead/taken over) |
| jobsinpods.com | skip | Redirects to legislate.ai (dead/taken over) |
| jobscribe.com | skip | Redirects to jobai.com (dead/taken over) |
| remotejobr.com | skip | Parked domain |
| remotejobsclub.com | skip | Unreachable |
| remotebaba.com | skip | Unreachable |
| goremote.io | skip | Unreachable |
| awesomejobs.io | skip | Unreachable |
| techjobs.com | skip | Unreachable |
| outsourcely.com | skip | Unreachable; also not relevant for PM roles |
| jobs.wordpress.net | skip | Not relevant for PM roles (developer-only) |
| jobs.laravel.io | skip | Not relevant for PM roles (developer-only) |
| rubynow.com | skip | Not relevant for PM roles (developer-only) |
| virtualassistantjobs.com | skip | Not relevant for PM roles (VA/outsourcing) |
| outsourcingjobs.ph | skip | Not relevant for PM roles (VA/outsourcing) |
| outsourcinginsight.com | skip | Not relevant for PM roles (outsourcing news) |
| cloudpeeps.com | skip | Not relevant for PM roles (freelance content/marketing) |
| simplycommunicate.com/jobs | skip | Communications roles, not PM/growth |

Revisit if a manual board ever exposes a JSON feed: add a function in `pipeline/sources/remote_boards.py`, register it in `pipeline/sources/__init__.py`, enable it in `config/sources.yaml`.
