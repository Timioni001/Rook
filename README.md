# Rook

**The operations agent that proves the fix.**

Rook is a web application a company connects to the software it already runs. Staff report a problem in one dashboard, Rook works out what is really going on across every system it touches, proposes a fix, waits for a person to approve anything that reaches someone outside the building, then checks the result against those systems and shows the proof. Anything it could not finish stays open, named, with the reason.

It does not replace a clinic's appointment book or a company's accounting software. It works across them, on the problems that otherwise need an employee to chase information and coordinate a fix by hand.

**What a company is buying**

- One place to see the problems nobody has finished yet.
- Connections into the software it already runs.
- An agent that investigates and coordinates the work across all of them.
- Approval controls, an audit trail, and proof the work actually landed.

Most agents in this space stop at a recommendation, and say why: nobody can prove the fix worked. Rook closes that gap. An incident closes only when independent checks pass on the live systems. We call this **Verified Closure**. Rook is built by the Keywarden team.

> Every system Rook connects to in this repository is a **sandboxed mock** with synthetic data and synthetic credentials (`sk_test_SYNTH_*`). No real patient, clinic, repository or cloud account is touched. This is a hackathon build for neatHack 2026 and is not production-ready.

## Who it is for

| Customer | The problems they lose people to | Rook today |
|---|---|---|
| Small and mid-sized clinics | A doctor off sick and a day of appointments to move; referrals, results and prescriptions marked done that never happened | **Doctor off sick** and **Care follow-up** playbooks |
| Growing companies | Leavers whose access lives on, leaked keys, services failing after a change | **Access & offboarding**, **Leaked credential** and **Service outage** playbooks |
| Any business with several systems | An order delayed between order management, inventory and delivery; anything where staff chase information across tools | Same engine; a new playbook plus the connectors it needs |

First version targets small and mid-sized clinics with one complete workflow. Real connectors where feasible, sandbox adapters for the demo.

We start with IT incident resolution and access management for growing companies. There's a clear buyer (the head of IT or ops), a problem they recognise, and a demo that shows Rook acting, recovering and verifying.

## Playbooks

The engine is the same for every incident: investigate, define closure, plan, authorize, execute, reconcile, verify, then close or escalate. A playbook (`rook/playbooks.py`) supplies what differs: the trigger, what to read, the remediation plan and the closure checks.

| Playbook | Trigger | What Rook does | Closure checks |
|---|---|---|---|
| **Access & offboarding** | A completed offboarding ticket | Disables leftover accounts, issues a replacement key, moves every service onto it, revokes the old key (with approval), and removes the leaked key from code | 13 |
| **Service outage** | A monitoring alert | Ties the alert to the deploy that caused it, pauses auto-deploy, rolls back to a known-good revision, checks that customers can check out, then resumes the pipeline with the bad revision blocked | 7 |
| **Leaked credential** | A secrets-scanner finding | Probes whether the leaked key still works, attributes it to an owner, finds every service using it, rotates and verifies each one, revokes the old key and clears the file | 3 to 11 |
| **Doctor off sick** | A doctor marked unavailable with patients booked in | Finds everyone affected, finds colleagues with room, moves each appointment, tells each person, and checks nobody was double-booked or left with a doctor who is not coming in. Anyone it cannot reach is left where they are and handed to reception | 2 per patient, plus 2 for the day |
| **Care follow-up** | A check of what a clinic says it has finished | Goes through every referral, result and prescription the record calls done, asks the clinic, pharmacy or doctor it was meant to reach, puts right the ones that never happened, and refuses to let the record say done while anything is missing | 13 |

## Old problems, and how Rook handles each

| The usual problem | What Rook does | Where |
|---|---|---|
| Offboarding disables the person but leaves their keys and side accounts alive | Starts from the closed offboarding ticket and sweeps the directory, three account systems and the vault | `playbooks.investigate` |
| Nobody knows everything that uses a key, and the vault's records are incomplete | Scans live app and cloud config by key fingerprint, and found `payments-worker`, which the vault never listed | `sandbox.dependents_of_fp` |
| Rotating a key causes an outage | Issues the replacement first, moves every service, verifies each one and revokes last. The order is enforced in code | `engine.enforce_order`, policy R4 |
| A botched update takes a service down mid-incident | Automatically rolls that service back to the old, still-valid key and holds the revocation | `Engine._compensate`, policy R7 |
| An outage alert fires and people spend the first half hour working out what changed | Lines the alert up against deploy history and config diffs, and names the suspect revision and the database it can't reach | `playbooks.investigate_outage` |
| A manual rollback gets overwritten by auto-deploy | Pauses the pipeline before rolling back. Policy refuses a rollback while auto-deploy would undo it | policy R4, `cloud.rollback` |
| The pipeline is frozen during an incident and nobody unfreezes it | Resuming the pipeline is part of the plan and a closure check. If Rook can't resume safely, it says so as a follow-up | `resume_pipeline` |
| "We rolled back, so it's fixed" | Closure needs the service healthy, errors normal, callers healthy and a synthetic order placed. If a rollback doesn't help, Rook escalates and says the deploy isn't the whole cause | `verification.outage_conditions` |
| Rolling back to a revision nobody trusts | Rolls back on its own only to a revision with a healthy track record. Anything else needs an approver | policy R8 |
| Scripts retry blindly and double-apply, or give up silently | Every failure is checkpointed and the real state inspected before a retry. Retries are bounded, then Rook escalates | `Engine._step` |
| The tool said "success" and the ticket was closed | Closure is decided by independent probes (authentication, health, regression, error rate, config), never by the tool's reply | `verification.py` |
| The leaked key stays in the repo and scanners keep firing | After revocation, Rook replaces the dead key in the file and flags the git history as a follow-up | `scrub_exposed_secret` |
| Orphaned accounts nobody owns | Rook flags them for a person and never acts on access it can't attribute | `follow_ups` |
| Risky actions without sign-off | Irreversible or unproven steps need an approver from the same org, and policy is re-checked just before execution | `policy.py` |
| A scanner finds a leaked key and the key is still alive months later | Rook probes the key, attributes it to an owner, finds every live user by fingerprint, rotates in a safe order and proves the old key is rejected | `playbooks.investigate_leak` |
| Rotating a key that was already revoked, for the sake of closing a ticket | Rook checks whether the key still works first. If it is already dead it refuses to rotate, cleans the file and says why | `LeakedSecret.plan`, `declines` |
| An agent acts on something it cannot explain | Everything Rook declined is reported next to what it did, with the policy rule. It never touches a credential it cannot attribute to an owner | `report.refusals`, policy R2 |
| Audit evidence is scattered and editable | Rook keeps an append-only, hash-chained audit log. A broken chain blocks closure. The evidence pack maps every closure check to an indicative SOC 2 and ISO 27001 control | `store.verify_chain`, `verification.CONTROLS`, `/evidence` |
| No incident metrics | Rook records time to contain (old key dead, or service restored), time to close, retries, rollbacks and checkpoints | `report.metrics` |

## Playbook 1: access & offboarding

A contractor, Jordan Doe, was offboarded and their directory account is disabled. Their payments API key is still active:

- they created it, and it is committed in `billing-api/.env.test`
- `billing-app` and `payments-worker` both authenticate with it, but the vault only records `billing-app`
- their cloud and project-tracker accounts were never disabled

Rook starts from the completed offboarding ticket and works through these steps:

1. **Investigate.** Rook reads the directory, accounts on three systems, vault metadata, live app and cloud config (it scans by fingerprint, so it finds the dependent that isn't recorded), and the commit history of the exposed file.
2. **Define closure first.** Rook writes 13 closure checks before it changes anything: the old key is rejected, the replacement works, nothing still uses the old key, and every dependent is configured, healthy and passing regression.
3. **Plan in a safe order.** The plan disables the leftover accounts, issues a replacement key, moves each dependent to it and only then revokes the old key. Code enforces this order whatever the planner proposes.
4. **Authorize.** Deterministic policy runs at plan time and again just before each action executes, against live state. Revocation can't be undone, so it waits for an approver from the incident's organisation.
5. **Execute, checkpoint and recover.** Each step persists to SQLite. When a tool call fails or times out, Rook inspects the real state before it decides whether a retry is safe. Retries reuse the same idempotency key.
6. **Verify independently.** Probes check authentication, health, regression suites and config fingerprints. A tool reporting success counts for nothing on its own.
7. **Clean up.** Rook removes the dead key from the file it leaked in, and rolls back any service that broke on the new key.
8. **Close or escalate.** The incident closes only when every invariant holds. Otherwise it escalates with the exact unmet checks, and Rook never retries forever.

## Playbook 2: service outage

`checkout-api` starts returning errors on 38% of requests, and `storefront` fails with it. Customers can't check out. Rook starts from the open alert and works through these steps:

1. **Investigate.** Rook reads the alert, live health and error rate, and the deploy history. Revision 42 went out one minute before the alert and changed `DB_HOST` to `db-replica-old`, which is decommissioned. Revision 41 ran healthy for 24 hours. Auto-deploy is on and still wants revision 42.
2. **Define closure first.** Seven checks: the service is healthy, the error rate is under 1%, it runs a known-good revision, `storefront` is healthy, a synthetic order goes through, the pipeline is running again, and revision 42 is blocked.
3. **Plan in a safe order.** Pause auto-deploy, roll back to revision 41, then resume auto-deploy with revision 42 blocked. Code enforces this order.
4. **Recover.** In the signature scenario the rollback call times out. Rook inspects the running revision, sees the rollback landed, and doesn't send it again.
5. **Close or escalate.** If rolling back doesn't restore the service (`outage_wrong_cause`), Rook escalates. It leaves the pipeline paused on purpose, and both points go into the follow-ups.

## Run it

Requirements: Python 3.10 to 3.13 (neatlogs doesn't support 3.14 yet) and Node 18 or later. **On Ubuntu/WSL, run `./scripts/setup-wsl.sh` once, then `./scripts/dev.sh` (local) or `./scripts/share.sh` (public link).**

```bash
pip install -r requirements.txt

# 1. Terminal demo (no server)
python -m rook.demo                            # offboarding: a 503 mid-remediation, then recovery
python -m rook.demo --scenario outage          # outage: bad deploy, ambiguous rollback, recovery
python -m rook.demo --scenario persistent      # Rook escalates instead of claiming success
python -m rook.demo --scenario leak            # leaked key: rotate, verify, revoke, clean the file
python -m rook.demo --scenario leak_unattributed   # Rook refuses to touch a key it cannot attribute
python -m rook.demo --scenario referral_clean  # a clinic: three things marked done that never happened
python -m rook.demo --scenario referral_critical   # an urgent result: Rook alerts a doctor and stops

# 2. API + dashboard
uvicorn rook.api:create_app --factory --port 8000
cd web && npm install && npm run dev            # http://localhost:3000
```

In the dashboard, pick an incident type and a scenario, click **Investigate**, then click **Run plan**. When Rook pauses, switch identity to **Priya (approver)** and approve the revocation. The run continues to closure. Switch to **Eve**, who belongs to a different company, and the incident disappears.

To trace to neatlogs, set `NEATLOGS_API_KEY` before starting the demo or the API. For the submission evidence, `./scripts/neatlogs-evidence.sh` sends the before/after pair and every playbook in one run, then tells you what to paste where. **To go live with no terminal (Render runs the agent, Cloudflare Pages serves the dashboard, neatlogs traces every incident), follow [deploy/README.md](deploy/README.md).**

### Keep a live demo usable at any hour

```bash
ROOK_API_ORIGIN=https://<service>.onrender.com ./scripts/deploy-keepwarm.sh   # cron worker, agent never sleeps
ROOK_API_ORIGIN=https://<service>.onrender.com ./scripts/deploy-pages.sh      # upload the dashboard, no Git build
python3 scripts/check-live.py https://<project>.pages.dev                     # run a real incident against the live site
```

`check-live.py` wakes the agent, loads the dashboard, runs an incident through to Verified Closure and prints `PASS`, so the link can be checked in one command before anyone arrives. The dashboard also detects a sleeping agent and waits for it instead of showing an error.

### One container

```bash
docker build -t rook . && docker run --rm -p 8000:8000 rook   # http://localhost:8000
```

### Tests and checks

```bash
python -m pytest -q                      # 120 tests
cd web && npm ci && npx tsc --noEmit && npm run build:static
bash scripts/build-pages.sh              # exactly what Cloudflare Pages runs
```

### Scenarios

Access & offboarding: `signature`, `clean`, `ambiguous_applied`, `ambiguous_lost`, `persistent`, `permission_denied`, `revoke_noop` (the vault says the key is revoked but it still works), `replacement_invalid`, `faulty_update`, `regression_fail`.
Service outage: `outage` (the rollback times out but did land), `outage_clean`, `outage_wrong_cause` (the rollback doesn't fix it), `outage_rollback_down`.
Leaked credential: `leak` (a config API fails once mid-rotation), `leak_clean`, `leak_already_revoked` (the key is already dead, so Rook refuses to rotate it), `leak_unattributed` (the key matches no credential, so Rook refuses to touch it).
Care follow-up: `referral_clean`, `referral` (the booking system fails once), `referral_critical` (one result is urgent, so Rook alerts a doctor and touches nothing else), `referral_unreachable` (the patient cannot be contacted, so Rook refuses to mark it done).
Doctor off sick: `cover_clean` (12 appointments, all moved and everyone told), `cover` (one move fails and is reconciled), `cover_short` (only four slots free, so eight stay open for reception), `cover_half`, `cover_unreachable` (one patient has no working number, so Rook leaves her appointment alone), `cover_nobody_reachable` (Rook moves nobody at all).
`referral_all_good` is the opposite case: everything the record claims really did happen, so Rook closes it with no actions.

### Situations you describe yourself

The scenarios above are written in advance. The dashboard also takes your own numbers, under **Or describe your own situation**, and the API takes them directly:

```bash
curl -X POST https://<your-service>/api/incidents \
  -H 'Authorization: Bearer demo-analyst-token' -H 'Content-Type: application/json' \
  -d '{"scenario":"cover_clean","setup":{"people_booked_in":7,"cover_slots":2,"people_we_cannot_reach":1,"one_step_fails":true}}'
```

Rook works the plan, the closure checks and the refusals out from whatever you describe. Every field is bounded and unknown fields are refused, so describing a situation cannot ask the service for data it does not have.
They are listed in `rook/sandbox.py:SCENARIOS`. Failures are injected deterministically per operation.

## Architecture

```
web/ (Next.js)  ──/api proxy──▶  rook/api.py (FastAPI, bearer auth, org scoping)
                                     │
                                     ▼
                          rook/engine.py  Rook: investigate → conditions → plan → policy
                          │      │        → execute → reconcile → verify → close/escalate
                          │   rook/playbooks.py  doctor off sick, care follow-up, offboarding, outage, leaked key
             rook/policy.py  rook/verification.py (independent observers)
                          │
                rook/sandbox.py  five stateful mock adapters, idempotency, failure injection
                          │
                rook/store.py    SQLite: incidents, actions, conditions, checkpoints,
                                 tool_calls, approvals, run leases, append-only audit
                rook/obs.py      spans → neatlogs (OpenTelemetry), redacted
```

| Adapter | What it holds | Operations used |
|---|---|---|
| Source host | accounts, repos, commit audit log | find exposed key by fingerprint, commit history, disable account |
| Cloud | accounts, services with env vars, revisioned deployments, deploy pipelines, databases | disable account, update service env, pause/resume pipeline, roll back, health and error-rate probes |
| Internal app | identity directory, app config, health, regression, synthetic checkout | update config, health, regression and synthetic-order probes |
| Project tracker | offboarding tickets, monitoring alerts, incident tickets | find completed offboardings and open alerts, open, comment on and close tickets |
| Vault | versioned credentials | issue replacement, revoke version, authentication probe |

Key safety properties are listed in [evidence/security-notes.md](evidence/security-notes.md).

## Partner tools

- **neatlogs**: one session per incident, with typed guardrail, tool and retriever spans, logged steps, a version tag and export masking. Every workflow phase is a span (`incident.run` WORKFLOW, `investigate`/`plan` AGENT, `policy.*`/`verify`/`closure.evaluate` GUARDRAIL, `execute` TOOL, `reconcile`/`checkpoint.restore` CHAIN). Attributes cover incident ID, adapter, action type, attempt, decision and verification result. Secret values are never included. The before/after comparison is the remediation-order change. [Evidence](evidence/neatlogs-traces.md).
- **Entire**: records the agent coding sessions that build Rook as checkpoints linked to commits, enabled from 2026-10-10 09:30 UTC. [How to inspect them](evidence/entire-workflow.md).
- **cfo.ai**: the business model behind Rook, written as a sheet of named assumptions so each one can be argued with: pricing against measured value, cost to serve (zero inference, 52 spans per incident), the year-one build, break-even at 22 clinics and where the plan runs out of room. [Evidence](evidence/cfo-ai-business-plan.md).
- **Cloudflare**: Cloudflare Pages serves the dashboard and forwards `/api/*` through a Pages Function to the agent on Render (`render.yaml`). A Cloudflare Worker on a cron trigger (`deploy/keepwarm`) keeps that agent awake so the public link answers immediately whenever someone opens it. Cloudflare Tunnel (`scripts/share.sh`) is the alternative for running from your own machine. All three are covered in [deploy/README.md](deploy/README.md).

## Limitations

- The adapters are in-process mocks. No real GitHub, cloud, vault or tracker is called.
- Demo bearer tokens are built in for local use. Set `KEYWARDEN_TOKENS` (JSON) and `KEYWARDEN_DEMO_TOKENS=0` anywhere shared.
- There is a single shared sandbox, so only one incident runs at a time.
- The optional model planner (`ROOK_PLANNER=llm`) covers the offboarding playbook and only proposes actions. Ordering, policy and verification stay deterministic.
- Five playbooks so far. Each new incident type is a new playbook plus the adapter operations it needs.
- The clinic playbooks are administrative only. Rook chases paperwork and contacts people; it never reads a result clinically or decides care, and anything urgent goes straight to a doctor. All patients, clinics and records in it are synthetic.
- The control mapping in the evidence pack is indicative. It is a starting point to confirm with an auditor, not a claim that an audit would pass.
