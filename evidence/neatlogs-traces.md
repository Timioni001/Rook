# neatlogs traces

## Status

| Item | Status |
|---|---|
| SDK installed (`neatlogs` 1.4.26) and initialised in the agent (`rook/obs.py:init_neatlogs`) | done |
| Spans for every workflow phase, with redaction | done, verified locally with an in-memory OpenTelemetry exporter (`tests/test_tracing.py`) |
| `ingest.neatlogs.com` reachable | yes. It answers `401` without a key, so the host is reachable and only wants credentials. An earlier build environment blocked it; that is no longer the limitation |
| Traces arriving in the neatlogs dashboard | **pending one run with the project key.** `./scripts/neatlogs-evidence.sh` does the whole thing in one command |
| Before/after trace links | **pending.** The numbers below are measured and reproducible; only the dashboard URLs are missing |

## What is traced

| Span | Kind | Useful attributes |
|---|---|---|
| `demo.incident` / `incident.start` / `incident.run` | WORKFLOW | `rook.incident`, `rook.scenario`, `rook.status`, `rook.steps` |
| `investigate`, `plan` | AGENT | accounts, active credentials, action count, planner |
| `discover.dependencies` | RETRIEVER | dependents, unrecorded dependents |
| `policy.decide`, `policy.recheck`, `approval.decide` | GUARDRAIL | action, action type, decision, rule, approver id |
| `execute` | TOOL | adapter, action type, target, attempt, outcome, replayed |
| `reconcile`, `checkpoint.restore` | CHAIN | attempt, applied, checkpoint, in-flight count |
| `verify`, `closure.evaluate`, `probe.dependent_health` | GUARDRAIL | pass/fail/inconclusive, checks passed / total, unhealthy dependents |

Errors set span status `ERROR` plus `rook.error`. Secret values are replaced with fingerprints, and sensitive attribute keys are dropped.

## neatlogs features used

| Feature (docs) | How Rook uses it | Checked by |
|---|---|---|
| Sessions (`trace(session_id=…)`) | Every trace of one incident (start, each run, each approval) shares `session_id = incident id`, so a whole incident replays as one session | `test_neatlogs_features_sessions_guardrails_tools` |
| End-user identity (`end_user_id`, metadata) | The human who started the incident or approved the revocation, with their org | same |
| Custom attributes: GUARDRAIL (`neatlogs.guardrail.input/passed/output`) | Policy decisions, the pre-execution re-check, approvals, each independent verification and the final Verified Closure verdict show as Passed or Blocked | same |
| Custom attributes: TOOL (`neatlogs.tool.name/description/parameters`) | Every adapter call, with its idempotency key and attempt number | same |
| Custom attributes: RETRIEVER | Dependency discovery: the query is the key fingerprint, the documents are the services found | same |
| `neatlogs.log` (`capture_logs=True`) | Timestamped steps: failed attempt, state inspection result, checkpoint resume | runtime only |
| `version` + tags | Each trace is tagged with the git commit, so before and after runs can be filtered apart | same |
| `mask` (client-side) + `pii_enabled` | The mask fingerprints any key value before export, in addition to the redaction applied when spans are created | `test_export_mask_replaces_secret_values` |
| Auto-instrumentation (`instrumentations=["anthropic"]`) | When the optional model planner is on, its calls become LLM spans | not exercised in tests (needs a model key) |

Detections and Alerts are configured in the neatlogs dashboard, not in code. Two worth adding once traces arrive: a regex detection on `sk_test_SYNTH` as a leak tripwire, which should never match, and a condition detection or alert on `neatlogs.guardrail.passed = false` for `closure.evaluate` spans, meaning an incident that wasn't closed.

## Before and after: remediation order

The change: the original agent rotated the key (revoking the old one) and only then repaired the app. The current agent issues a replacement, moves every dependent, verifies each one and only then revokes. `probe.dependent_health` runs after every workflow step and records whether a dependent was broken.

Measured with `python -m rook.demo`, running commit `c2e097d` for before and the current branch for after. Raw JSON is in [runs/](runs/):

| Scenario | Before (`c2e097d`) | After | Re-measured |
|---|---|---|---|
| One transient failure | closed, **3 steps with billing-app down** | closed, **0 steps with any dependent down** | yes, 2026-10-11 |
| Persistent failure | left **open** with billing-app broken for **6 steps**, old key revoked, repair failed | escalated with **0 steps down**: revocation never ran | yes, 2026-10-11 |
| Dependents found | 1 (vault metadata only) | 2 (live config scan also finds payments-worker) | — |

Note that the before seed had no `payments-worker`. The "dependents found" row describes the discovery method, not a like-for-like run.

One number needs reading carefully. `dependent_outage_steps` is 2 on the `outage` scenario, which
looks like a regression and is not: in that playbook the service is already down when the incident
opens, because that is the incident. The before/after comparison is the credential rotation
scenarios, where the agent itself caused the outage it is being measured on.

## Per-playbook trace volume, measured

Counted with an in-memory OpenTelemetry exporter, so these are the spans a real export would send.

| Playbook / scenario | Spans | Actions | Tool calls | Closure checks |
|---|---|---|---|---|
| offboarding / signature | 43 | 7 | 8 | 13 |
| outage / outage | 20 | 3 | 3 | 7 |
| leak / leak | 35 | 5 | 6 | 11 |
| care / referral_clean | 50 | 9 | 9 | 13 |
| cover / cover_clean | 130 | 24 | 24 | 26 |
| cover / cover_short | 50 | 8 | 8 | 10 |

Mean 52 spans per incident. That figure is what the cost-per-customer line in
[cfo-ai-business-plan.md](cfo-ai-business-plan.md) is built on.

## Producing the dashboard traces

One command, with the project key in the environment:

```bash
read -rs NEATLOGS_API_KEY && export NEATLOGS_API_KEY   # not echoed, not written to history
./scripts/neatlogs-evidence.sh
```

It runs the two "before" scenarios from a git worktree at `c2e097d` and every playbook as it is
now, labelled `before` and `after`. The working tree is never checked out or modified. Both
versions run on the same virtual environment, because the dependencies did not change.

Verified end to end without a key: the worktree builds, both versions run, and the numbers below
come straight out of it. Only the export step needs the key.

Each run prints `neatlogs_delivery` counters; `span_export_failures` should be 0. Open the traces
under workflow `rook-incident-response`, filter by the `rook.label` tag, and paste the URLs below.

| Trace | URL |
|---|---|
| before / transient | _pending_ |
| before / persistent | _pending_ |
| after / signature | _pending_ |
| after / persistent | _pending_ |
| after / cover_clean (a doctor off sick) | _pending_ |
| after / cover_unreachable (Rook refuses to move one appointment) | _pending_ |
| after / referral_critical (Rook alerts a doctor and stops) | _pending_ |
