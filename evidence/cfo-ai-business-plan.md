# cfo.ai business plan

The team completed the cfo.ai setup and business plan before this build. This file records what has actually been checked. No numbers here are invented, and none will be until the plan itself is available.

| Status | Value |
|---|---|
| cfo.ai account set up | reported by the team, **not independently verified** |
| Business plan created | reported by the team, **not independently verified** |
| Plan contents accessed (pricing, revenue, costs, margins, runway, CAC, risks) | **no.** No export, link or screenshot is in the repository or project files, and the build environment can't reach cfo.ai |
| Submission evidence saved | **no** |

## Still needed

A share link, export (PDF/CSV) or screenshots of the existing plan. Once it's available, this file will summarise the plan's own assumptions and point to the artifact. Anything in the implementation that differs from a plan assumption will be listed as a discrepancy and raised with the team rather than changed.

## Product facts that may matter to the plan (from the code, not financial assumptions)

- Rook makes no model calls in the default configuration. The rule-based planner is deterministic, so per-incident inference cost is zero unless `ROOK_PLANNER=llm` is set, which adds one planning call per incident.
- Observability cost scales with spans. Measured demo runs emit 46 (clean), 51 (signature) and 53 (persistent failure) spans per incident.
- Infrastructure is a single container (FastAPI + SQLite + static dashboard). The demo runs on the team's own machine and is shared through a free Cloudflare quick tunnel, so the hackathon demo has no hosting cost (`deploy/README.md`).

## What to enter in cfo.ai (facts only; the team sets the prices)

- **Product:** Rook, B2B software that resolves IT incidents and access tasks for growing companies and proves each fix was completed correctly.
- **Segments:** startups and SMEs (offboarding, access, routine IT), mid-size companies (outages, recovery, compliance), enterprises (complex multi-system incident response).
- **Playbooks shipped:** credential offboarding, service outage (bad deploy rollback).
- **Cost per incident today:** no model calls by default; 46 to 53 observability spans per incident; one small container per customer (FastAPI + SQLite).
- **Hosting for the demo:** none, because it runs on the team's machine behind a free Cloudflare quick tunnel.
- **Left to the team:** price per seat or per incident, team size and salaries, customer targets. Rook's repository has no source for these.

Plan link: _paste the cfo.ai share link here once it exists._
