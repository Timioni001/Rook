# neatlogs traces

## Status

| Item | Status |
|---|---|
| SDK installed (`neatlogs` 1.4.26) and initialised in the agent (`rook/obs.py:init_neatlogs`) | done |
| Spans for every workflow phase, with redaction | done, verified locally with an in-memory OpenTelemetry exporter (`tests/test_tracing.py`) |
| Traces arriving in the neatlogs dashboard | **not yet verified.** The build environment's network policy blocks `ingest.neatlogs.com`, so a run with a project key from a machine that can reach it is still needed |
| Before/after trace links | **pending.** The numbers below are measured, but the trace links don't exist yet |

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

Measured with `python -m rook.demo`, running commit `0817443` for before and the current branch for after. Raw JSON is in [runs/](runs/):

| Scenario | Before (`0817443`) | After |
|---|---|---|
| One transient failure | closed, **3 steps with billing-app down** | closed, **0 steps with any dependent down** |
| Persistent failure | **billing-app left broken** (6 steps down, old key revoked, repair failed) | escalated with **0 steps down**: revocation never ran |
| Dependents found | 1 (vault metadata only) | 2 (live config scan also finds payments-worker) |

Note that the before seed had no `payments-worker`. The "dependents found" row describes the discovery method, not a like-for-like run.

## Producing the dashboard traces (needs a machine that can reach neatlogs)

```bash
export NEATLOGS_API_KEY=...            # project key; never commit it
# before
git checkout 0817443 && pip install -r requirements.txt
ROOK_DEMO_LABEL=before python -m rook.demo --scenario transient
ROOK_DEMO_LABEL=before python -m rook.demo --scenario persistent
# after
git checkout keywarden-build-v7m54f && pip install -r requirements.txt
ROOK_DEMO_LABEL=after python -m rook.demo --scenario signature
ROOK_DEMO_LABEL=after python -m rook.demo --scenario persistent
```

Each run prints `neatlogs_delivery` counters (`span_export_failures` should be 0). Open the traces under workflow `rook-incident-response`, filter by `rook.label`, and paste the trace URLs or screenshots here.

| Trace | URL |
|---|---|
| before / transient | _pending_ |
| before / persistent | _pending_ |
| after / signature | _pending_ |
| after / persistent | _pending_ |
