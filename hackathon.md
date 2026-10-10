# Build log: Keywarden / Rook (neatHack 2026)

Times are UTC. The event started 2026-10-10 07:00 UTC, and the deadline is 2026-10-12 18:25 UTC. The commit history is the primary record.

## 2026-10-10

**07:38–07:48: first version uploaded (17 commits).** This was a credential-offboarding agent with a state machine, idempotent sandbox, crash recovery, verification and 22 passing tests.

**08:02: neatlogs tracing and a measurable baseline (`0817443`).**
- `obs.span()` now emits neatlogs/OpenTelemetry spans with redacted attributes.
- `python -m rook.demo` probes dependent health after every step. The baseline showed that the original order (rotate, then repair) broke billing-app for 3 steps in the transient scenario and left it broken under persistent failure.

**08:09: replace before revoking (`f316a7c`).**
- Rewrote the five adapters around the real incident. The contractor's key is used by two services, and one of them is missing from vault metadata.
- The plan is now issue → update dependents → revoke, enforced in code. Policy runs at plan time and before every action, and revocation needs an approver.
- Every failure is reconciled against real state before a retry. A run lease stops concurrent executors, and restarts resume from the checkpoint.
- Result: 0 outage steps in both the transient and persistent scenarios. The persistent case now escalates with billing healthy.

**08:11: API hardening (`7cc1239`).** Bearer auth on every route, org-scoped incidents (404 across orgs), roles, strict bodies, body and rate limits, generic errors. Added 30 API tests.

**08:18: dashboard (`ccaea0e`).** The full flow works in a browser: run, 503, recovery, approval as a different user, verified closure.

**08:25: docs and evidence.** README, `evidence/` (test results, demo script, security notes, before/after runs) and honest status pages for neatlogs dashboard traces, Entire checkpoints and the cfo.ai plan, which are still pending.

**08:35–09:05: Rook name, Cloudflare and features for long-standing problems.**
- Product renamed to Rook. A Cloudflare Pages Function proxies the static dashboard's `/api` to the AWS container, checked locally with `wrangler pages dev`.
- New: automatic rollback of a service broken by its update, leaked-key removal from the repo after revocation, ownerless-account follow-ups, a hash-chained audit log that blocks closure if tampered with, a Markdown evidence pack, and time-to-contain metrics. 69 tests.
- Dashboard restyled after the team's reference design.

## Open items

- Export real neatlogs traces from a machine that can reach `ingest.neatlogs.com`, then add the links.
- Entire: the team decided not to use it for this build.
- Link the existing cfo.ai plan.
- Record the demo video and post #neatHack updates.
