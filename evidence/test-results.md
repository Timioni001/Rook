# Test results

Generated from real runs in the build environment on 2026-10-10 (UTC). Re-run with the commands below.

## Backend: `python -m pytest -v`

Result: **58 passed** at the time of the raw output below. The current branch has **80**: 2 neatlogs feature tests, an evidence-pack API test, 6 tests for rollback, repo cleanup, ownerless accounts, a tampered audit log and incident metrics, and 11 service-outage tests in `tests/test_outage.py`. They pass on Python 3.13. The one warning comes from Starlette's test client.

### Required scenarios → tests

| # | Scenario | Test(s) |
|---|---|---|
| 1 | Successful end-to-end resolution | `test_end_to_end_resolution_with_evidence`, `test_full_flow_over_http` |
| 2 | Transient failure, then recovery | `test_transient_failure_recovers_after_reconciliation` |
| 3 | Restart from a saved checkpoint | `test_restart_from_checkpoint` |
| 4 | Duplicate execution / idempotency | `test_duplicate_execution_is_idempotent`, `test_concurrent_runs_are_refused`, `test_double_run_and_closed_incident_conflicts` |
| 5 | Unauthorized action denied | `test_unauthorized_action_denied`, `test_approval_requires_approver_role_and_same_org`, `test_roles_enforced` |
| 6 | Tampered request identity rejected | `test_identity_fields_in_body_rejected[*]`, `test_created_by_comes_from_token` |
| 7 | Ambiguous outcome reconciled before retry | `test_ambiguous_outcome_reconciled[ambiguous_applied/ambiguous_lost]` |
| 8 | Persistent failure escalated safely | `test_persistent_failure_escalates`, `test_permanent_failure_escalates` |
| 9 | Multiple dependents in a safe order | `test_dependents_updated_before_revocation`, `test_revocation_without_dependent_steps_is_blocked`, `test_new_dependent_appearing_before_revocation_blocks_it` |
| 10 | Failed regression prevents closure | `test_failed_regression_prevents_closure` |
| 11 | Old credential still valid blocks closure | `test_old_credential_still_valid_blocks_closure`, `test_success_response_without_state_change_fails[*]` |
| 12 | Audit report matches actions | `test_audit_report_matches_actions` |
| 13 | Secrets absent from traces and logs | `test_secrets_absent_everywhere`, `test_secret_values_never_reach_trace_attributes`, `test_no_secrets_in_api_responses` |
| 14 | API authorization on every sensitive route | `test_every_route_requires_authentication[*]` (10 routes), `test_other_org_cannot_see_or_touch_incident[*]` (7 routes) |

### Raw output

```
tests/test_api.py::test_full_flow_over_http PASSED                       [  1%]
tests/test_api.py::test_every_route_requires_authentication[get-/api/me] PASSED [  3%]
tests/test_api.py::test_every_route_requires_authentication[get-/api/scenarios] PASSED [  5%]
tests/test_api.py::test_every_route_requires_authentication[get-/api/incidents] PASSED [  6%]
tests/test_api.py::test_every_route_requires_authentication[post-/api/incidents] PASSED [  8%]
tests/test_api.py::test_every_route_requires_authentication[get-/api/incidents/{iid}] PASSED [ 10%]
tests/test_api.py::test_every_route_requires_authentication[get-/api/incidents/{iid}/events] PASSED [ 12%]
tests/test_api.py::test_every_route_requires_authentication[post-/api/incidents/{iid}/run] PASSED [ 13%]
tests/test_api.py::test_every_route_requires_authentication[post-/api/incidents/{iid}/cancel] PASSED [ 15%]
tests/test_api.py::test_every_route_requires_authentication[post-/api/incidents/{iid}/actions/{aid}/approve] PASSED [ 17%]
tests/test_api.py::test_every_route_requires_authentication[post-/api/incidents/{iid}/actions/{aid}/reject] PASSED [ 18%]
tests/test_api.py::test_other_org_cannot_see_or_touch_incident[get-/api/incidents/{iid}] PASSED [ 20%]
tests/test_api.py::test_other_org_cannot_see_or_touch_incident[get-/api/incidents/{iid}/events] PASSED [ 22%]
tests/test_api.py::test_other_org_cannot_see_or_touch_incident[post-/api/incidents/{iid}/run] PASSED [ 24%]
tests/test_api.py::test_other_org_cannot_see_or_touch_incident[post-/api/incidents/{iid}/cancel] PASSED [ 25%]
tests/test_api.py::test_other_org_cannot_see_or_touch_incident[post-/api/incidents/{iid}/actions/{aid}/approve] PASSED [ 27%]
tests/test_api.py::test_other_org_cannot_see_or_touch_incident[post-/api/incidents/{iid}/actions/{aid}/reject] PASSED [ 29%]
tests/test_api.py::test_other_org_incident_list_is_empty PASSED          [ 31%]
tests/test_api.py::test_roles_enforced PASSED                            [ 32%]
tests/test_api.py::test_identity_fields_in_body_rejected[owner] PASSED   [ 34%]
tests/test_api.py::test_identity_fields_in_body_rejected[org] PASSED     [ 36%]
tests/test_api.py::test_identity_fields_in_body_rejected[created_by] PASSED [ 37%]
tests/test_api.py::test_identity_fields_in_body_rejected[approver] PASSED [ 39%]
tests/test_api.py::test_identity_fields_in_body_rejected[principal] PASSED [ 41%]
tests/test_api.py::test_created_by_comes_from_token PASSED               [ 43%]
tests/test_api.py::test_validation_and_limits PASSED                     [ 44%]
tests/test_api.py::test_rate_limit PASSED                                [ 46%]
tests/test_api.py::test_errors_do_not_leak_internals PASSED              [ 48%]
tests/test_api.py::test_double_run_and_closed_incident_conflicts PASSED  [ 50%]
tests/test_api.py::test_no_secrets_in_api_responses PASSED               [ 51%]
tests/test_scenarios.py::test_end_to_end_resolution_with_evidence PASSED [ 53%]
tests/test_scenarios.py::test_transient_failure_recovers_after_reconciliation PASSED [ 55%]
tests/test_scenarios.py::test_restart_from_checkpoint PASSED             [ 56%]
tests/test_scenarios.py::test_duplicate_execution_is_idempotent PASSED   [ 58%]
tests/test_scenarios.py::test_concurrent_runs_are_refused PASSED         [ 60%]
tests/test_scenarios.py::test_unauthorized_action_denied PASSED          [ 62%]
tests/test_scenarios.py::test_approval_requires_approver_role_and_same_org PASSED [ 63%]
tests/test_scenarios.py::test_rejected_revocation_escalates PASSED       [ 65%]
tests/test_scenarios.py::test_ambiguous_outcome_reconciled[ambiguous_applied-False] PASSED [ 67%]
tests/test_scenarios.py::test_ambiguous_outcome_reconciled[ambiguous_lost-True] PASSED [ 68%]
tests/test_scenarios.py::test_persistent_failure_escalates PASSED        [ 70%]
tests/test_scenarios.py::test_permanent_failure_escalates PASSED         [ 72%]
tests/test_scenarios.py::test_dependents_updated_before_revocation PASSED [ 74%]
tests/test_scenarios.py::test_revocation_without_dependent_steps_is_blocked PASSED [ 75%]
tests/test_scenarios.py::test_new_dependent_appearing_before_revocation_blocks_it PASSED [ 77%]
tests/test_scenarios.py::test_failed_regression_prevents_closure PASSED  [ 79%]
tests/test_scenarios.py::test_old_credential_still_valid_blocks_closure PASSED [ 81%]
tests/test_scenarios.py::test_success_response_without_state_change_fails[replacement_invalid-issue_replacement] PASSED [ 82%]
tests/test_scenarios.py::test_success_response_without_state_change_fails[faulty_update-update_dependent] PASSED [ 84%]
tests/test_scenarios.py::test_inconclusive_observation_rejects_closure PASSED [ 86%]
tests/test_scenarios.py::test_missing_conditions_reject_closure PASSED   [ 87%]
tests/test_scenarios.py::test_audit_report_matches_actions PASSED        [ 89%]
tests/test_scenarios.py::test_secrets_absent_everywhere PASSED           [ 91%]
tests/test_scenarios.py::test_invalid_state_transition_rejected PASSED   [ 93%]
tests/test_scenarios.py::test_cancellation_stops_before_mutation PASSED  [ 94%]
tests/test_tracing.py::test_workflow_spans_exported_through_neatlogs PASSED [ 96%]
tests/test_tracing.py::test_secret_values_never_reach_trace_attributes PASSED [ 98%]
tests/test_tracing.py::test_span_records_errors PASSED                   [100%]
======================== 58 passed, 1 warning in 6.15s =========================
```

## Frontend

```
$ cd web && npx tsc --noEmit
(no output: no type errors)
$ npx next build
 ✓ Compiled successfully
Route (app)        Size     First Load JS
┌ ○ /              ~7.5 kB  ~95 kB
```

## Browser run

A Playwright script drove the real dashboard against the real API. It created a `signature` incident, ran it, waited for the approval pause, switched to the approver identity, approved, and waited for `Closed · verified`. The screenshots are in [screenshots/](screenshots/). At 390 px the page width stayed 390 px, so there was no horizontal scroll.

## Single-container check

`STATIC_EXPORT=1 npx next build` produced `web/out`. Uvicorn served it at `/` (200, title "Keywarden · Rook"), with `/api/health` 200, an unknown `/api/*` 404 and an unauthenticated `/api/me` 401. The same Playwright flow ran end to end against that single origin.

`docker build` itself couldn't be completed in the build environment because both Docker Hub and ECR Public returned 429 (rate limited). The image hasn't been built yet, so the first build will happen on the deploy machine.
