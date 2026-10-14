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


## Scope-driven sources (2026-10-14)

Probed against Yashvi's scope (PM / growth / founder's office / TPM; contract and fractional; paid remote internships and fresher roles; Bengaluru, NCR or remote-India/worldwide). Nothing here needs a login. "Survivors" is the count that passed the gates when run alone with `--only <name> --no-verify` on 2026-10-14.

| Source | Category | How read | Status | URL |
|---|---|---|---|---|
| Unstop | fresher / internship / India startups | Public JSON API (`/api/public/opportunity/search-result`), jobs + internships, paid only | added (`unstop`, 46 survivors) | https://unstop.com/jobs |
| Internshala | fresher / paid internship / India | Server-rendered listing cards, 13 pages, paid only | added (`internshala`, 13 survivors) | https://internshala.com/jobs/product-manager-jobs/ |
| Wellfound | India startups (PM, CoS, founder's office, growth, TPM) | Public role pages, Apollo state in `__NEXT_DATA__`; India + Gurgaon/Delhi/Noida; 1s between requests. Wellfound's terms discourage scraping, so keep it at this light weekly-ish volume and switch off if it starts returning bot checks | added (`wellfound`, 19 survivors) | https://wellfound.com/role/l/product-manager/india |
| Weekday | India startups / curated | Sitemaps by function, then `JobPosting` JSON-LD for recent title-matched pages (cap 150) | added (`weekday`, 42 survivors) | https://jobs.weekday.works |
| Remote Rocketship | remote worldwide + India-eligible | Server-rendered Next.js data (`initialJobOpenings`); only page 1 for India (its `/api` is disallowed), 2 pages worldwide | added (`remoterocketship`, 24 survivors) | https://remoterocketship.com/country/india/jobs/product-manager |
| Hasjob | India startups | Atom feed, about 16 postings | added but disabled (`hasjob`, 0 survivors) | https://hasjob.co/feed |
| Khosla, Sapphire, 8VC, Techstars, FirstMark, DCVC, Bonfire, Greycroft | VC portfolio boards (global, India/remote subset) | Getro, added to `getro.boards` | added (all 8 verified to respond) | jobs.khoslaventures.com, jobs.sapphireventures.com, jobs.8vc.com, jobs.techstars.com, jobs.firstmark.com, jobs.dcvc.com, jobs.bonfirevc.com, jobs.greycroft.com |
| Chiratae, Battery, Felicis, Initialized, USV | VC portfolio boards (Chiratae is India: 190+ India roles) | Consider, added to `consider.boards` | added (all verified) | careers.chiratae.com, jobs.battery.com, jobs.felicis.com, jobs.initialized.com, jobs.usv.com |
| Hirist | India tech/product | Result feed is client-rendered; sitemap has slugs only; robots asks for 10s crawl delay | manual weekly | https://www.hirist.tech/k/product-manager-jobs |
| iimjobs | India, MBA/senior PM, strategy, CoS | Same stack as Hirist; sitemap is slugs for all-time jobs | manual weekly | https://www.iimjobs.com/k/product-manager-jobs |
| Fractional Jobs | fractional / part-time PM, ops, growth | Homepage HTML lists about 58 jobs (`/jobs/<title>-at-<company>`), no JSON-LD or feed, mostly US companies | manual weekly | https://www.fractionaljobs.io |
| Lenny's Jobs | PM, growth (global) | JS app, no public feed | manual weekly | https://www.lennysjobs.com |
| Naukri | India all-round | JS app; the search API refuses plain requests (400) and I did not work around it | manual weekly | https://www.naukri.com/product-manager-jobs-in-bengaluru |
| Apna, Shine, Monster India, Freshersworld | India fresher / general | Large HTML pages, no JSON-LD or public API | manual weekly | https://apna.co/jobs, https://www.shine.com, https://www.monsterindia.com, https://www.freshersworld.com |
| a16z, Greylock job boards | VC portfolio (global) | Custom JS apps, not Getro or Consider | manual weekly | https://jobs.a16z.com, https://jobs.greylock.com |
| Contra | freelance / contract | JS app, opportunities need an account | login-needed | https://www.contra.com/opportunities |
| Braintrust | contract / freelance | Job browse needs an account to match; page is JS | login-needed | https://www.braintrust.com/jobs |
| Flexiple | freelance (mostly engineering) | Apply as talent, no public job list | login-needed | https://www.flexiple.com/jobs |
| Toptal, Turing | freelance talent networks | Vetted application, no public job list | login-needed | https://www.toptal.com, https://www.turing.com |
| Mercor | contract (mostly AI-training work) | JS app, needs an account | login-needed | https://www.mercor.com/jobs |
| Freelancer.com | freelance gigs | RSS works but is global micro-gigs, almost never PM/growth | skip (low signal) | https://www.freelancer.com/rss.xml |
| Upwork | freelance | RSS returns 403 | blocked | https://www.upwork.com |
| Foundit | India all-round | 403 on plain requests | blocked | https://www.foundit.in |
| Indeed, Jooble, Careerjet, startup.jobs, productjobs.io, Remotive web pages | various | 403 or "verify you are human" checks, not bypassed | blocked | https://in.indeed.com, https://in.jooble.org, https://www.careerjet.co.in, https://startup.jobs |
| Glassdoor India | India all-round | Bot-protected search pages | blocked | https://www.glassdoor.co.in |
| Uplers, Jobspresso | India / remote | Uplers `/jobs` is 404; Jobspresso feed had no items and its pages are old | dead | https://uplers.com, https://jobspresso.co/feed/ |
| Elevation, Nexus, Matrix (Z47), Stellaris, Kalaari, Lightspeed India | Indian VC portfolio boards | No public portfolio job board found on their sites (Lightspeed is already covered via jobs.lsvp.com) | dead | https://elevationcapital.com, https://nexusvp.com, https://www.z47.com |
