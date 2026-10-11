# Handoff: continuing the Rook build

Read this first when picking the build up in a new coding session. Deadline: **Mon Oct 12 2026, 23:55 IST (18:25 UTC)**. NeatHack scoring: agent 30, tools 25 (neatlogs, Entire, cfo.ai), video 20, build in public 15, originality 10.

## What Rook is

A web application a company connects to the software it already runs. Staff report a problem in one dashboard; Rook investigates across every connected system, proposes a fix, waits for approval on anything that reaches someone outside the building, then proves the result held ("Verified Closure"). It works across existing systems rather than replacing any of them. Every run goes through the same steps: investigate, define closure conditions, plan, policy check, execute in a safe order, reconcile, verify, then close or escalate.

| Playbook | Trigger | Key scenarios |
|---|---|---|
| Credential offboarding | a leaver | `signature`, `clean`, `faulty_update`, `persistent` |
| Service outage | a monitoring alert | `outage`, `outage_clean`, `outage_wrong_cause`, `outage_rollback_down` |
| Leaked credential | a secrets-scanner finding | `leak`, `leak_clean`, `leak_already_revoked`, `leak_unattributed` |
| Care follow-up | a check of what a clinic says it finished | `referral_clean`, `referral`, `referral_critical`, `referral_unreachable` |
| Doctor off sick | a doctor marked unavailable with patients booked in | `cover_clean`, `cover`, `cover_short`, `cover_unreachable` |

## Map of the code

- `rook/playbooks.py`: per-playbook investigation, plan, closure conditions and copy. Registry `PLAYBOOKS`.
- `rook/engine.py`: the shared run loop, ordering, retries, reconcile-before-retry, report and evidence pack.
- `rook/policy.py`: rules R0 to R10. R9 stops a record being marked done while anything is missing; R10 pins every care action to the patient on its own record. R4 is safe order; R8 means rollback goes only to a known-good revision, or needs approval.
- `rook/verification.py`: observers that check the real sandbox state after a fix, plus `CONTROLS`, the indicative SOC 2 / ISO 27001 mapping used by the evidence pack.
- Refusals: each playbook's `declines(inc, acts)` plus blocked and pending actions, collected in `Engine.report` as `refusals`.
- `rook/sandbox.py`: synthetic systems (source host, cloud, app and directory, tracker, vault) and the `SCENARIOS`. Synthetic credentials only.
- `rook/api.py`: FastAPI app. `Setup` on `POST /api/incidents` takes a caller-described situation; every field is bounded and extras are refused (`uvicorn rook.api:create_app --factory`). Demo bearer tokens, hash-chained audit in SQLite.
- `rook/obs.py`: neatlogs spans. On when `NEATLOGS_API_KEY` is set.
- `web/`: Next.js 14 dashboard. `STATIC_EXPORT=1` builds `web/out`, which the API serves. `web/functions/api` is the Cloudflare Pages proxy.

## Run and test (Ubuntu 26.04 on WSL)

```bash
./scripts/setup-wsl.sh        # once: Node 22, uv + Python 3.13 venv (neatlogs needs < 3.14), npm ci, cloudflared
./scripts/dev.sh              # API :8000 + dashboard http://localhost:3000
.venv/bin/pytest -q           # 120 tests
.venv/bin/python -m rook.demo --scenario outage
```

Going live is described in `deploy/README.md`: Render (`render.yaml`) runs the agent and Cloudflare Pages serves the dashboard, both set up in the browser. `./scripts/share.sh` is the terminal alternative.

```bash
bash scripts/build-pages.sh                                 # exactly what Cloudflare Pages runs
python3 scripts/check-live.py https://<project>.pages.dev    # real incident against the live site; prints PASS
ROOK_API_ORIGIN=https://<svc>.onrender.com ./scripts/deploy-pages.sh      # upload the dashboard directly
ROOK_API_ORIGIN=https://<svc>.onrender.com ./scripts/deploy-keepwarm.sh   # cron worker, stops Render sleeping
```

The Pages project must have its root directory set to `web` (build command `npm run build:static`) or left empty (build command `npm run build`); output directory `out` either way. Never `npx next build` -- that is what broke the first production build.

## Rules for this repo

- No AI-assistant attribution in commits, PR text or code (no co-author lines, no session links, no model names). The exception is Entire records: `.claude/` hooks, `.entire/`, `Entire-Checkpoint` trailers and checkpoints.
- Never commit secrets. Keys live in `.env` (gitignored) or in the host's settings.
- Use synthetic systems and credentials only. Rook never runs arbitrary shell commands.
- Don't invent evidence or financial numbers. cfo.ai figures come from the team's plan.
- Every behaviour change gets a test. Keep `evidence/` in sync with what the code really does.

## Entire

Turn it on locally with `entire enable --agent <your agent>` so new sessions keep producing checkpoints. Locally, `git push` can carry the checkpoint refs. Earlier checkpoints were exported as files under `.entire/checkpoints/` (with `scripts/export-entire-checkpoints.py`), and `evidence/entire-workflow.md` lists them.

## Still to do

1. Go live via `deploy/README.md`, run `scripts/check-live.py` against the public address, then record real neatlogs trace links in `evidence/`.
2. cfo.ai: enter the facts in `evidence/cfo-ai-business-plan.md`, then add the plan's share link there and in the README.
3. Demo video (about 3 minutes): the outage run, then `outage_wrong_cause` escalating, then the evidence pack.
4. Build-in-public posts with #neatHack (drafts were made in the project chat).
5. Make the repo public before submitting.
