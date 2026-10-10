# Demo scenario and script

## What the main demo shows

Scenario `signature`: billing-app's config API returns one 503 while Rook moves the app to the new key.

The real terminal run (`python -m rook.demo`, full JSON in [runs/after-signature.json](runs/after-signature.json)) produced:

- status `closed_verified`, 13/13 closure checks passing
- 8 tool calls: 1 failed (503), 1 retry, 0 steps where a dependent was down. The 8th call removes the dead key from `billing-api/.env.test`
- Audit sequence around the failure: `executing (attempt 1)` → `transient_failure` → checkpoint saved → `reconciled_not_applied` (Rook confirmed the config was unchanged, so a retry was safe) → `executing (attempt 2)` → `executed` → `verification_verified`

The other outcomes, from real runs in [runs/](runs/):

| Scenario | Result | Why |
|---|---|---|
| `persistent` | escalated, 9/13 checks | billing-app update failed 4 times, so revocation never ran and billing stayed healthy |
| `ambiguous_applied` | closed, 13/13 | Timeout, but inspection showed the change had landed, so there was no retry |
| `revoke_noop` | escalated, 11/13 | The vault said "revoked" but the old key still authenticates |
| `regression_fail` | escalated, 12/13 | billing-app is healthy but its regression suite fails |
| `faulty_update` | escalated, 9/13 | billing-app stored a wrong key and was down for 1 step. Rook rolled it back to the old, still-valid key and held the revocation |

## Service outage playbook

Real terminal runs (`python -m rook.demo --scenario <name>`, full JSON in [runs/](runs/)):

| Scenario | Result | Why |
|---|---|---|
| `outage` | closed, 7/7 checks | 3 tool calls, 1 failed. The rollback call timed out, but Rook read the running revision, saw the rollback had landed and didn't send it again. Auto-deploy is back on with revision 42 blocked |
| `outage_wrong_cause` | escalated, 1/7 | The rollback landed but the service stayed down, so Rook escalated: the deploy isn't the whole cause. The pipeline stays paused on purpose, and both points are listed as follow-ups |
| `outage_rollback_down` | escalated, 0/7 | The rollback API failed 4 times. Rook stopped there and left revision 42 visible as still running instead of claiming a fix |

In these runs `dependent_outage_steps` counts the workflow steps where checkout-api or storefront were down. For an outage that's the time until the rollback lands, not harm Rook caused.

## Video script (under 3 minutes)

1. **0:00–0:15 Problem.** "Growing companies handle IT incidents by hand: someone investigates, someone fixes, and the ticket gets closed when the tool says success. Rook does the work and proves it." Show the two incident types and the sandbox banner.
2. **0:15–0:40 Investigate (offboarding).** Start the `signature` incident. Point at the graph (person → accounts, key → billing-app and payments-worker → repo) and the findings. Call out that "payments-worker isn't in vault metadata; Rook found it by scanning config."
3. **0:40–0:55 Plan and policy.** Walk the plan in safe order: replace, move both services, then revoke. Note the 13 closure checks defined before any change.
4. **0:55–1:25 Failure and recovery.** Click **Run plan**. The timeline shows the 503. In the failure card, show the checkpoint, the state inspection ("did not take effect, so a retry is safe"), attempt 2 succeeding and the independent verification.
5. **1:25–1:45 Approval.** Rook pauses at revocation. As Sam the approve button isn't there. Switch to Priya (approver) and approve. The step runs and the old key is rejected. Show 13/13 checks and the evidence pack.
6. **1:45–2:25 Service outage.** Switch to **Service outage**, scenario `outage`. Findings: revision 42 went out one minute before the alert and points at a decommissioned database, and auto-deploy would undo a rollback. Run it: pause, rollback (it times out, and Rook confirms it landed instead of resending), resume with revision 42 blocked. 7/7 checks, including "a test order goes through".
7. **2:25–2:40 Honest failure.** Run `outage_wrong_cause`: the rollback doesn't help, so Rook escalates, keeps the pipeline paused and says why.
8. **2:40–3:00 Partners.** Show the neatlogs trace tree (sessions per incident, guardrail spans, before/after), the Entire checkpoints for the build and the cfo.ai plan.
