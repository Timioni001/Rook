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
- Infrastructure is a single FastAPI process with SQLite plus a Next.js frontend.
