# Security notes

Keywarden is a sandbox: all five adapters are in-process mocks holding synthetic keys (`sk_test_SYNTH_*`). Nothing here is production-ready, and these notes describe what the build does and what it doesn't do.

## Agent safety

- **No arbitrary execution.** Rook can only perform four action types (`policy.ALLOWED`) against named services. There is no shell, network or file tool.
- **Least privilege and scope.** Every action must target a resource owned by the incident subject. If ownership can't be established, Rook blocks the action (fail closed, rule R2).
- **Safe order enforced in code.** `engine.enforce_order` adds issue → update → revoke edges whatever the planner (rule-based or model) proposes. Policy R4 blocks revocation while any live config still uses the old key. This is re-checked just before execution, so a dependent that appears late blocks it (`test_new_dependent_appearing_before_revocation_blocks_it`).
- **Human approval for irreversible steps.** Revocation needs an approver from the incident's org. The approver's identity comes from their authenticated principal and is stored in `approvals`.
- **Ambiguous outcomes.** Any timeout or transient error moves the action to `unknown`. Rook then probes real state before it decides between verified, safe retry and escalation. If it can't tell, it stops.
- **Bounded retries and steps.** `max_retries=3` and `max_steps=200`. Exhaustion leads to `failed` and escalation.
- **Verification is separate from execution.** Observers in `verification.py` never read adapter responses.
- **Append-only, hash-chained audit.** SQLite triggers reject `UPDATE`/`DELETE` on `audit`. Each event also stores `sha256(previous hash + event)`, so even someone who bypasses the triggers breaks the chain. A broken chain fails the `audit_chain_intact` invariant and blocks closure (`test_tampered_audit_log_blocks_closure`).
- **Compensation, not hope.** If a service breaks on the new key, Rook restores its previous key, but only while that key is still valid (policy R7). Revocation is then held back.
- **No action on unattributable access.** Ownerless accounts are reported as follow-ups and never touched.

## API

- Bearer token on every route except `/api/health`, including the `/evidence` download. Tokens are looked up by SHA-256 digest with constant-time comparison, and the principal (id, org, roles) comes only from the token.
- Request bodies are strict (`extra="forbid"`). `owner`, `org`, `created_by`, `approver` and similar fields are rejected with 422.
- Object-level authorization: an incident from another org returns 404 on every route, so its existence isn't leaked either.
- Roles: `viewer` (read), `analyst` (create, run, cancel), `approver` (approve, reject).
- Limits: 8 KB request body (413), 30 changes/min and 900 reads/min per principal (429; reads are looser because the dashboard polls), strict id formats, scenario names from an enum.
- Errors: unhandled exceptions return `{"detail": "internal error"}` without a stack trace. Responses set `nosniff`, `no-store` and `no-referrer`.
- One executor per incident (SQLite lease). A second run gets 409.

## Secrets

- Stored audit events, checkpoints, tool outcomes and approvals go through `store.redact`, which replaces key values with `fp:` fingerprints.
- Trace attributes are redacted the same way. Keys matching `secret|token|password|authorization|api_key|value` are dropped before export (`test_secret_values_never_reach_trace_attributes`).
- The neatlogs API key is read from the environment and never logged or committed.

## Known limitations

- Demo tokens are built in for local runs. Disable them with `KEYWARDEN_DEMO_TOKENS=0` and set `KEYWARDEN_TOKENS`.
- There's no TLS termination, CSRF protection (bearer tokens only, no cookies) or token rotation.
- The sandbox is a single shared state, so one incident runs at a time.
- The rate limiter is in-memory and per process.
