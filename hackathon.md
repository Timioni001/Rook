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

**09:06–: restructured as B2B IT incident resolution.**
- Rook is now an operations agent for growing companies. The engine stayed the same; incident types became playbooks (`rook/playbooks.py`). Credential offboarding is one playbook.
- New **service outage** playbook: alert → deploy correlation → pause pipeline → rollback to a known-good revision → resume with the bad revision blocked, with 7 closure checks and policy rules R4 (no rollback while auto-deploy would undo it) and R8 (only roll back unattended to a proven revision). 80 tests.
- Builds now target Ubuntu on WSL: `scripts/setup-wsl.sh`, `scripts/dev.sh`, LF line endings enforced, and a Python 3.13 venv via uv, since neatlogs doesn't support 3.14.

**09:30: Entire on.** The team reversed the earlier skip. Entire now records the agent sessions and links them to commits through `Entire-Checkpoint` trailers.

**18:30: no AWS.** The team didn't qualify for the AWS credit, so the Lightsail deploy is gone. The live demo now runs locally and is shared through Cloudflare Tunnel (`scripts/share.sh`). The WSL setup script no longer collides with an existing NodeSource Node install.

**19:56: the Cloudflare Pages build failed.** `Couldn't find any \`pages\` or \`app\` directory`. The Pages project's root directory had never been set to `web`, so the build ran at the repo root: it pip-installed `requirements.txt` for nothing, `npx` found no local Next and downloaded a different major of it, and there was no `app/` to build.

**20:40: the deploy is now hard to get wrong, and the demo stays up.**
- `scripts/build-pages.sh` installs the pinned dependencies and always builds inside `web/`. It mirrors the export and the `/api` function to the repo root, so the Pages project works with its root directory set to `web` *or* left empty. `.node-version` pins Node 22. Next moved to 14.2.35, the patched release in that line.
- The `/api` Pages Function retries a sleeping backend, never replays a write, and says what to configure when it has no agent behind it. Checked locally with `wrangler pages dev`: static, authed GET, POST with a body, 401 passthrough, no-origin and dead-agent cases.
- A Cloudflare Worker on a 5-minute cron (`deploy/keepwarm`) keeps the Render instance from sleeping, so the public link answers at once whenever judging happens. The dashboard also waits out a cold start instead of showing an error.
- `scripts/deploy-pages.sh` uploads the dashboard straight from WSL if the Git build misbehaves. `scripts/check-live.py` runs a real incident against the live address and prints PASS, including the approval step.

**21:26: second Pages build failed the same way.** The project's build command was still `STATIC_EXPORT=1 npx next build` at the repository root, which cannot work from there whatever the repository contains. Render, meanwhile, came up: `scripts/check-live.py https://rook-qswm.onrender.com` closes an offboarding incident verified, approval step included.

**22:00: the dashboard deploy no longer depends on the Cloudflare build settings.**
- `scripts/deploy-pages.sh` creates the Pages project, compiles the agent's address into a staged copy of the `/api` proxy and uploads it. No build command, no root directory, no environment variables. The committed proxy keeps its empty default, so nothing in git changes.
- Fixed a proxy bug this surfaced: the agent's responses are compressed, and forwarding the client's `accept-encoding` left the body and the `content-encoding` header disagreeing, so the page arrived as noise. The proxy now negotiates compression itself and drops the framing headers the runtime has already consumed. Verified in a browser: the staged bundle, served by the real Workers runtime against the live Render agent, runs an outage incident to Verified Closure with no console errors.

## Open items

- Export real neatlogs traces from a machine that can reach `ingest.neatlogs.com`, then add the links.
- Link the existing cfo.ai plan.
- Record the demo video and post #neatHack updates.
