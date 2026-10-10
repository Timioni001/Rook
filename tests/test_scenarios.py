import json
import threading
import pytest
from rook import verification
from rook.domain import Action, InvalidTransition, Principal, Status
from rook.engine import Engine, RuleBasedPlanner, RunInProgress, SimulatedCrash, make_action
from rook.sandbox import Sandbox, OLD
from rook.store import Store, redact

nosleep = lambda s: None
APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])
ANALYST = Principal(id="u-analyst", org="acme", roles=["analyst"])


def mk(path=":memory:", scenario="clean", failures=None, flags=None, **kw):
    st = Store(path)
    sb = Sandbox(st, scenario=scenario, failures=failures, flags=flags)
    return st, sb, Engine(st, sb, sleep=nosleep, **kw)


def acts(st, iid):
    return {(a.type, a.target): a for a in st.actions(iid)}


def revoke_of(st, iid):
    return next(a for a in st.actions(iid) if a.type == "revoke_credential")


def go(e, approve=True):
    """Start, run until approval is needed, approve the revocation, run to the end."""
    inc = e.start()
    rep = e.run(inc.id)
    if approve and rep["status"] == "awaiting_approval":
        e.approve(inc.id, revoke_of(e.store, inc.id).id, APPROVER)
        rep = e.run(inc.id)
    return inc.id, rep


def events(st, iid):
    return [x["event"] for x in st.audit_events(iid)]


# 1. successful end-to-end resolution (+ discovery, graph, conditions defined first)
def test_end_to_end_resolution_with_evidence():
    st, sb, e = mk()
    inc = e.start()
    assert inc.subject == "ident-jdoe"            # found from the completed offboarding ticket
    cred = next(r for r in inc.relationships if r["rel"] == "owns_credential")
    assert cred["cred"] == "cred-pay" and cred["created_by"] == "jdoe"
    assert cred["dependents"] == ["app:billing-app", "cloud:payments-worker"]
    assert cred["unrecorded_dependents"] == ["cloud:payments-worker"]
    assert cred["exposed_in"] == ["billing-api/.env.test"]
    kinds = {n["kind"] for n in inc.graph["nodes"]}
    assert {"identity", "account", "credential", "dependent", "repo"} <= kinds
    assert all(c.result is None for c in st.conditions(inc.id))
    rep = e.run(inc.id)
    assert rep["status"] == "awaiting_approval" and sb.vault.authenticate_fp(cred["fp"])
    e.approve(inc.id, revoke_of(st, inc.id).id, APPROVER)
    rep = e.run(inc.id)
    assert rep["status"] == "closed_verified" and not rep["unresolved"]
    assert all(c["result"] is True for c in rep["conditions"])
    assert all(rep["invariants"].values())
    ev = events(st, inc.id)
    assert ev.index("closure_conditions_defined") < ev.index("executing")
    assert not sb.vault.authenticate_fp(cred["fp"])
    assert sb.s["pm"]["tickets"][inc.ticket]["status"] == "done"
    assert st.incident(inc.id).closed_at


# 2. transient failure followed by recovery (reconcile first, then retry)
def test_transient_failure_recovers_after_reconciliation():
    st, sb, e = mk(scenario="signature")
    iid, rep = go(e)
    assert rep["status"] == "closed_verified"
    a = acts(st, iid)[("update_dependent", "app:billing-app")]
    assert a.retries == 1 and a.status == Status.verified
    ev = events(st, iid)
    i = ev.index("transient_failure")
    assert ev[i + 1] == "reconciled_not_applied" and ev[i + 2] == "executing"
    assert [c["outcome"] for c in st.tool_calls(iid) if c["action"] == a.id] == ["transient", "ok"]


# 3. restart from a saved checkpoint after a crash mid-action
def test_restart_from_checkpoint(tmp_path):
    p = str(tmp_path / "k.db")
    st, sb, e = mk(p, crash_after=4)          # crash right after billing-app's config is changed
    inc = e.start()
    with pytest.raises(SimulatedCrash):
        e.run(inc.id)
    mid = acts(Store(p), inc.id)[("update_dependent", "app:billing-app")]
    assert mid.status == Status.executing     # persisted mid-flight
    st2 = Store(p)
    sb2 = Sandbox(st2)                         # fresh process: state comes only from SQLite
    e2 = Engine(st2, sb2, sleep=nosleep)
    rep = e2.run(inc.id)
    assert "checkpoint_restored" in events(st2, inc.id)
    assert "reconciled_verified" in events(st2, inc.id)
    e2.approve(inc.id, revoke_of(st2, inc.id).id, APPROVER)
    rep = e2.run(inc.id)
    assert rep["status"] == "closed_verified"
    assert sb2.s["mutations"] == 9            # ticket open + 6 actions + 2 ticket updates: nothing applied twice


# 4. duplicate execution and idempotency
def test_duplicate_execution_is_idempotent():
    st, sb, e = mk()
    iid, rep = go(e)
    m = sb.s["mutations"]
    rep2 = e.run(iid)                          # second run of a finished incident
    assert rep2["status"] == "closed_verified" and sb.s["mutations"] == m
    r1 = sb.vault.issue_replacement("cred-pay", "k1")
    r2 = sb.vault.issue_replacement("cred-pay", "k1")
    assert r2["replayed"] and r1["version"] == r2["version"]


def test_concurrent_runs_are_refused():
    st, sb, e = mk()
    inc = e.start()
    assert st.acquire_run(inc.id, "other-worker")
    with pytest.raises(RunInProgress):
        e.run(inc.id)
    assert sb.s["mutations"] == 1              # only the ticket


# 5. unauthorized action denied
def test_unauthorized_action_denied():
    st, sb, e = mk()
    bad = make_action("x", 99, "issue_replacement", "cred-reports", {"service": "vault", "old_version": 1})
    worse = make_action("x", 98, "delete_repo", "billing-api", {"service": "github"})
    inc = e.start(extra_actions=[bad, worse])
    a = acts(st, inc.id)
    assert a[("issue_replacement", "cred-reports")].status == Status.blocked
    assert a[("delete_repo", "billing-api")].policy["rule"] == "R1-allowlist"
    e.run(inc.id)
    assert sb.vault.latest("cred-reports")["v"] == 1


def test_approval_requires_approver_role_and_same_org():
    st, sb, e = mk()
    inc = e.start()
    rev = revoke_of(st, inc.id)
    with pytest.raises(PermissionError):
        e.approve(inc.id, rev.id, ANALYST)
    with pytest.raises(PermissionError):
        e.approve(inc.id, rev.id, Principal(id="mallory", org="evil", roles=["approver"]))
    assert revoke_of(st, inc.id).status == Status.needs_approval
    assert [x["decision"] for x in st.approvals(inc.id)] == ["refused_by_policy"] * 2


def test_rejected_revocation_escalates():
    st, sb, e = mk()
    inc = e.start()
    e.run(inc.id)
    e.reject(inc.id, revoke_of(st, inc.id).id, APPROVER, "change freeze")
    rep = e.run(inc.id)
    assert rep["status"] == "escalated"
    assert any(c["id"] == "cred-pay-old-rejected" and c["result"] is False for c in rep["conditions"])


# 7. ambiguous tool outcome reconciled before retry
@pytest.mark.parametrize("scenario,retried", [("ambiguous_applied", False), ("ambiguous_lost", True)])
def test_ambiguous_outcome_reconciled(scenario, retried):
    st, sb, e = mk(scenario=scenario)
    iid, rep = go(e)
    assert rep["status"] == "closed_verified"
    a = acts(st, iid)[("update_dependent", "cloud:payments-worker")]
    outcomes = [c["outcome"] for c in st.tool_calls(iid) if c["action"] == a.id]
    assert outcomes == (["timeout", "ok"] if retried else ["timeout"])
    ev = events(st, iid)
    assert ("reconciled_not_applied" in ev) == retried
    assert ("reconciled_verified" in ev) == (not retried)


# 8. persistent failure escalated safely, no infinite retry, no revocation
def test_persistent_failure_escalates():
    st, sb, e = mk(scenario="persistent")
    iid, rep = go(e)
    a = acts(st, iid)[("update_dependent", "app:billing-app")]
    assert a.status == Status.failed and a.retries == 4
    assert rep["status"] == "escalated"
    assert revoke_of(st, iid).status in (Status.needs_approval, Status.blocked)
    assert sb.vault.authenticate_fp(next(r for r in st.incident(iid).relationships
                                         if r["rel"] == "owns_credential")["fp"])   # never broke billing
    assert sb.health("app:billing-app")
    assert "failed_retries_exhausted" in events(st, iid) and "escalated" in events(st, iid)


def test_permanent_failure_escalates():
    st, sb, e = mk(scenario="permission_denied")
    iid, rep = go(e)
    assert acts(st, iid)[("disable_account", "jdoe")].status in (Status.failed, Status.verified)
    assert rep["status"] == "escalated" and rep["closure_blocked_reason"]


# 9. multiple dependents handled in a safe order
def test_dependents_updated_before_revocation():
    st, sb, e = mk()
    inc = e.start()
    plan = st.actions(inc.id)
    idx = {(a.type, a.target): i for i, a in enumerate(plan)}
    assert idx[("issue_replacement", "cred-pay")] < idx[("update_dependent", "app:billing-app")]
    assert idx[("update_dependent", "cloud:payments-worker")] < idx[("revoke_credential", "cred-pay")]
    rev = revoke_of(st, inc.id)
    assert len(rev.depends_on) == 3
    e.run(inc.id)
    e.approve(inc.id, rev.id, APPROVER)
    e.run(inc.id)
    order = [x["data"]["action"] for x in st.audit_events(inc.id) if x["event"] == "verification_verified"]
    assert order.index(rev.id) == len(order) - 1


def test_revocation_without_dependent_steps_is_blocked():
    class NoUpdates(RuleBasedPlanner):
        def plan(self, rel, iid):
            return [a for a in super().plan(rel, iid) if a.type != "update_dependent"]
    st, sb, e = mk(planner=NoUpdates())
    iid, rep = go(e)
    rev = revoke_of(st, iid)
    assert rev.status == Status.blocked and rev.policy["rule"] == "R4-safe-order"
    assert sb.health("app:billing-app") and rep["status"] == "escalated"


def test_new_dependent_appearing_before_revocation_blocks_it():
    st, sb, e = mk()
    inc = e.start()
    e.run(inc.id)
    e.approve(inc.id, revoke_of(st, inc.id).id, APPROVER)
    sb.s["apps"]["reports-app"]["config"] = {"PAYMENTS_KEY": OLD}   # someone wires the old key in meanwhile
    rep = e.run(inc.id)
    rev = revoke_of(st, inc.id)
    assert rev.status == Status.blocked and "reports-app" in rev.policy["reason"]
    assert "policy_recheck_blocked" in events(st, inc.id) and rep["status"] == "escalated"


# 10. failed regression test prevents closure
def test_failed_regression_prevents_closure():
    st, sb, e = mk(scenario="regression_fail")
    iid, rep = go(e)
    assert rep["status"] != "closed_verified"
    assert any(c["id"] == "app:billing-app-regression" and c["result"] is False for c in rep["conditions"])


# 11. old credential still valid -> independent verification blocks closure
def test_old_credential_still_valid_blocks_closure():
    st, sb, e = mk(scenario="revoke_noop")
    iid, rep = go(e)
    rev = revoke_of(st, iid)
    assert rev.status == Status.failed      # vault said "revoked"; the probe says the key still works
    assert rep["status"] == "escalated"
    assert any(c["id"] == "cred-pay-old-rejected" and c["result"] is False for c in rep["conditions"])


@pytest.mark.parametrize("scenario,failing", [("replacement_invalid", "issue_replacement"),
                                              ("faulty_update", "update_dependent")])
def test_success_response_without_state_change_fails(scenario, failing):
    st, sb, e = mk(scenario=scenario)
    iid, rep = go(e)
    assert any(a.type == failing and a.status == Status.failed for a in st.actions(iid))
    assert rep["status"] == "escalated"
    assert sb.vault.authenticate_fp(next(r for r in st.incident(iid).relationships
                                         if r["rel"] == "owns_credential")["fp"])   # old key not revoked


def test_inconclusive_observation_rejects_closure(monkeypatch):
    def boom(sb, a):
        raise RuntimeError("observer unavailable")
    monkeypatch.setitem(verification.OBSERVERS, "dependent_healthy", boom)
    st, sb, e = mk()
    iid, rep = go(e)
    assert rep["status"] != "closed_verified"
    assert any(c["result"] is None for c in rep["conditions"])


def test_missing_conditions_reject_closure():
    st, sb, e = mk()
    iid, rep = go(e)
    st._x("DELETE FROM conditions WHERE incident_id=?", (iid,))
    rep2 = e.report(iid, live=True)
    assert rep2["status"] != "closed_verified" and not rep2["invariants"]["closure_conditions_defined"]


# 12. audit report matches actual actions and outcomes
def test_audit_report_matches_actions():
    st, sb, e = mk(scenario="signature")
    iid, rep = go(e)
    db = {a.id: a.status.value for a in st.actions(iid)}
    assert {a["id"]: a["status"] for a in rep["actions"]} == db
    evs = st.audit_events(iid)
    verified = {x["data"].get("action") for x in evs if x["event"] in ("verification_verified", "reconciled_verified")}
    assert {k for k, v in db.items() if v == "verified"} <= verified
    executed = [x["data"]["action"] for x in evs if x["event"] == "executing"]
    assert len(executed) == len(st.tool_calls(iid)) == rep["metrics"]["tool_calls"]
    assert st.incident(iid).status == rep["status"]
    assert len(st.approvals(iid)) == 1 and st.approvals(iid)[0]["by"] == "u-approver"
    with pytest.raises(Exception):
        st._x("DELETE FROM audit")
    with pytest.raises(Exception):
        st._x("UPDATE audit SET event='x'")


# 13. secret values are absent from storage, reports and traces
def test_secrets_absent_everywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOK_TRACE", "1")
    monkeypatch.setenv("ROOK_TRACE_DIR", str(tmp_path))
    assert "sk_test_SYNTH" not in redact({"k": "x sk_test_SYNTH_cred-pay_v2 y"})
    st, sb, e = mk(scenario="signature")
    iid, rep = go(e)
    blob = json.dumps([st.audit_events(iid), st.checkpoints(iid), st.tool_calls(iid), st.approvals(iid), rep,
                       st.incident(iid).model_dump(), [a.model_dump() for a in st.actions(iid)]], default=str)
    assert "sk_test_SYNTH" not in blob
    assert "sk_test_SYNTH" not in (tmp_path / "rook-trace.jsonl").read_text()


def test_invalid_state_transition_rejected():
    a = Action(id="x", incident_id="i", type="disable_account", target="t", idem_key="k", status=Status.verified)
    with pytest.raises(InvalidTransition):
        a.move(Status.executing)


def test_cancellation_stops_before_mutation():
    st, sb, e = mk()
    inc = e.start()
    e.cancel()
    rep = e.run(inc.id)
    assert sb.s["mutations"] == 1 and rep["status"] != "closed_verified"
    assert "cancelled" in events(st, inc.id)
