# Demo scenario and script

## What the main demo shows

Scenario `signature`: billing-app's config API returns one 503 while Rook moves the app to the new key.

The real terminal run (`python -m rook.demo`, full JSON in [runs/after-signature.json](runs/after-signature.json)) produced:

- status `closed_verified`, 12/12 closure checks passing
- 7 tool calls: 1 failed (503), 1 retry, 0 steps where a dependent was down
- Audit sequence around the failure: `executing (attempt 1)` → `transient_failure` → checkpoint saved → `reconciled_not_applied` (Rook confirmed the config was unchanged, so a retry was safe) → `executing (attempt 2)` → `executed` → `verification_verified`

The other outcomes, from real runs in [runs/](runs/):

| Scenario | Result | Why |
|---|---|---|
| `persistent` | escalated, 9/12 checks | billing-app update failed 4 times, so revocation never ran and billing stayed healthy |
| `ambiguous_applied` | closed, 12/12 | Timeout, but inspection showed the change had landed, so there was no retry |
| `revoke_noop` | escalated, 11/12 | The vault said "revoked" but the old key still authenticates |
| `regression_fail` | escalated, 11/12 | billing-app is healthy but its regression suite fails |

## Video script (under 3 minutes)

1. **0:00–0:15 Problem.** "A contractor left yesterday. Their account is disabled, but the payments API key they created still works. It's in a repo, and two services depend on it." Show the sandbox banner.
2. **0:15–0:45 Investigate.** Start the `signature` incident. Point at the graph (person → accounts, key → billing-app and payments-worker → repo) and the findings. Call out that "payments-worker isn't in vault metadata; Rook found it by scanning config."
3. **0:45–1:05 Plan and policy.** Walk the plan in safe order: replace, move both services, then revoke. Note the 12 closure checks defined before any change.
4. **1:05–1:40 Failure and recovery.** Click **Run plan**. The timeline shows the 503. In the failure card, show the checkpoint, the state inspection ("did not take effect, so a retry is safe"), attempt 2 succeeding and the independent verification.
5. **1:40–2:05 Approval.** Rook pauses at revocation. As Sam (analyst) the approve button isn't there. Switch to Priya (approver) and approve. The step runs and the old key is rejected.
6. **2:05–2:25 Verified Closure.** Show 12/12 checks with evidence and the closed ticket. Switch to Eve (other org) and the incident isn't visible.
7. **2:25–2:50 Partners.** Show the neatlogs trace tree (before/after outage numbers), the Entire checkpoint for the build and the cfo.ai plan.
8. **2:50–3:00 Persistent failure.** Optionally show `python -m rook.demo --scenario persistent` printing `escalated`.
