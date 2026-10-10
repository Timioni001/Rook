# Keywarden

**Rook investigates, contains and verifies.**

Keywarden is a security incident-response product built around one agent, **Rook**. Rook doesn't stop at recommending a fix. It investigates a credential incident, takes authorized actions in a safe order, recovers from failed actions and checks the result independently. It closes the incident only when evidence shows every closure condition holds. We call this **Verified Closure**.

> Every integration in this repository is a **sandboxed mock** with synthetic credentials (`sk_test_SYNTH_*`). Keywarden is a hackathon build for neatHack 2026 and is not production-ready.

## The incident

A contractor, Jordan Doe, was offboarded and their directory account is disabled. Their payments API key is still active:

- they created it, and it is committed in `billing-api/.env.test`
- `billing-app` and `payments-worker` both authenticate with it, but the vault only records `billing-app`
- their cloud and project-tracker accounts were never disabled

Rook starts from the completed offboarding ticket and works through these steps:

1. **Investigate.** Rook reads the directory, accounts on three systems, vault metadata, live app and cloud config (it scans by fingerprint, so it finds the dependent that isn't recorded), and the commit history of the exposed file.
2. **Define closure first.** Rook writes 12 closure checks before it changes anything: the old key is rejected, the replacement works, nothing still uses the old key, and every dependent is configured, healthy and passing regression.
3. **Plan in a safe order.** The plan disables the leftover accounts, issues a replacement key, moves each dependent to it and only then revokes the old key. Code enforces this order whatever the planner proposes.
4. **Authorize.** Deterministic policy runs at plan time and again just before each action executes, against live state. Revocation can't be undone, so it waits for an approver from the incident's organisation.
5. **Execute, checkpoint and recover.** Each step persists to SQLite. When a tool call fails or times out, Rook inspects the real state before it decides whether a retry is safe. Retries reuse the same idempotency key.
6. **Verify independently.** Probes check authentication, health, regression suites and config fingerprints. A tool reporting success counts for nothing on its own.
7. **Close or escalate.** The incident closes only when every invariant holds. Otherwise it escalates with the exact unmet checks, and Rook never retries forever.

## Run it

Requirements: Python 3.10 to 3.13 and Node 18 or later.

```bash
pip install -r requirements.txt

# 1. Terminal demo (no server). Signature scenario: a 503 mid-remediation, then recovery.
python -m rook.demo
python -m rook.demo --scenario persistent      # Rook escalates instead of claiming success

# 2. API + dashboard
uvicorn rook.api:create_app --factory --port 8000
cd web && npm install && npm run dev            # http://localhost:3000
```

In the dashboard, pick a scenario and click **Investigate offboarded contractor**, then **Run plan**. When Rook pauses, switch identity to **Priya (approver)** and approve the revocation. The run continues to closure. Switch to **Eve**, who belongs to a different company, and the incident disappears.

To trace to neatlogs, set `NEATLOGS_API_KEY` before starting the demo or the API. See [evidence/neatlogs-traces.md](evidence/neatlogs-traces.md).

### One container (what runs on AWS)

```bash
docker build -t keywarden . && docker run --rm -p 8000:8000 keywarden   # http://localhost:8000
```

### Tests and checks

```bash
python -m pytest -q                      # 60 tests
cd web && npx tsc --noEmit && npx next build
```

### Scenarios

`signature`, `clean`, `ambiguous_applied`, `ambiguous_lost`, `persistent`, `permission_denied`, `revoke_noop` (the vault says the key is revoked but it still works), `replacement_invalid`, `faulty_update`, `regression_fail`. They are listed in `rook/sandbox.py:SCENARIOS`. Failures are injected deterministically per operation.

## Architecture

```
web/ (Next.js)  ──/api proxy──▶  rook/api.py (FastAPI, bearer auth, org scoping)
                                     │
                                     ▼
                          rook/engine.py  Rook: investigate → conditions → plan → policy
                          │      │        → execute → reconcile → verify → close/escalate
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
| Cloud | accounts, services with env vars | disable account, update service env |
| Internal app | identity directory, app config, health, regression | update config, health and regression probes |
| Project tracker | offboarding and security tickets | find completed offboardings, open, comment on and close tickets |
| Vault | versioned credentials | issue replacement, revoke version, authentication probe |

Key safety properties are listed in [evidence/security-notes.md](evidence/security-notes.md).

## Partner tools

- **neatlogs**: one session per incident, with typed guardrail, tool and retriever spans, logged steps, a version tag and export masking. Every workflow phase is a span (`incident.run` WORKFLOW, `investigate`/`plan` AGENT, `policy.*`/`verify`/`closure.evaluate` GUARDRAIL, `execute` TOOL, `reconcile`/`checkpoint.restore` CHAIN). Attributes cover incident ID, adapter, action type, attempt, decision and verification result. Secret values are never included. The before/after comparison is the remediation-order change. [Evidence](evidence/neatlogs-traces.md).
- **Entire**: checkpoints linking commits to the build sessions. [Evidence](evidence/entire-workflow.md).
- **cfo.ai**: the business plan behind Keywarden's pricing and costs. [Evidence](evidence/cfo-ai-business-plan.md).
- **AWS (optional, hackathon credit)**: hosts the public demo as one Lightsail container, so judges get a live link and the live instance exports neatlogs traces. See [deploy/README.md](deploy/README.md).

## Limitations

- The adapters are in-process mocks. No real GitHub, cloud, vault or tracker is called.
- Demo bearer tokens are built in for local use. Set `KEYWARDEN_TOKENS` (JSON) and `KEYWARDEN_DEMO_TOKENS=0` anywhere shared.
- There is a single shared sandbox, so only one incident runs at a time.
- The optional model planner (`ROOK_PLANNER=llm`) only proposes actions. Ordering, policy and verification stay deterministic.
