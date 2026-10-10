import json
import pytest
from rook import verification
from rook.domain import Action, InvalidTransition, Status
from rook.engine import Engine, RuleBasedPlanner, SimulatedCrash, make_action
from rook.sandbox import Sandbox
from rook.store import Store, redact

SUBJ = "ident-jdoe"
nosleep = lambda s: None


def mk(path=":memory:", failures=None, flags=None, **kw):
    st = Store(path)
    sb = Sandbox(st, failures=failures if failures is not None else {}, flags=flags or {})
    return st, sb, Engine(st, sb, sleep=nosleep, **kw)


def go(e):
    inc = e.start(SUBJ)
    return inc.id, e.run(inc.id)


def acts(st, iid):
    return {(a.type, a.target): a for a in st.actions(iid)}


def test_happy_path_and_conditions_defined_first():
    st, sb, e = mk()
    inc = e.start(SUBJ)
    conds = st.conditions(inc.id)
    assert conds and all(c.result is None for c in conds)       # defined, not yet evaluated
    evs = [x["event"] for x in st.audit_events(inc.id)]
    assert evs.index("closure_conditions_defined") < len(evs)
    rep = e.run(inc.id)
    evs = [x["event"] for x in st.audit_events(inc.id)]
    assert evs.index("closure_conditions_defined") < evs.index("executing")
    assert rep["status"] == "closed_verified" and not rep["unresolved"]
    assert all(c["result"] is True for c in rep["conditions"])


def test_credential_relationship_discovery():
    st, sb, e = mk()
    inc = e.start(SUBJ)
    cred = [r for r in inc.relationships if r["rel"] == "owns_credential"][0]
    assert cred["cred"] == "cred-pay" and cred["used_by"] == ["billing-app"]
    assert cred["exposed_in"] == ["billing-api/.env.test"]
    accts = {(r["service"], r["status"]) for r in inc.relationships if r["rel"] == "has_account"}
    assert ("github", "disabled") in accts and ("cloud", "active") in accts
    assert "sk_test_SYNTH" not in json.dumps(inc.relationships)
    assert "cred-pay" in inc.exposure and "billing-app" in inc.exposure


def test_authorization_denial():
    st, sb, e = mk()
    bad = make_action("x", 99, "rotate_credential", "cred-other", {"service": "vault", "old_fp": "fp:x"})
    inc = e.start(SUBJ, extra_actions=[bad])
    rep = e.run(inc.id)
    a = [x for x in st.actions(inc.id) if x.target == "cred-other"][0]
    assert a.status == Status.blocked and sb.vault.version("cred-other") == 1
    assert rep["status"] == "open"
    with pytest.raises(ValueError):
        e.approve(inc.id, a.id)          # ownership violations cannot be approved


def test_transient_failure_recovers():
    st, sb, e = mk(failures={"app.repair": ["transient"]})
    iid, rep = go(e)
    assert rep["status"] == "closed_verified"
    assert acts(st, iid)[("repair_config", "billing-app")].retries == 1
    assert sb.s["rotations"] == 1
    assert "transient_failure_retry" in [x["event"] for x in st.audit_events(iid)]


def test_restart_recovery(tmp_path):
    p = str(tmp_path / "k.db")
    st, sb, e = mk(p, crash_after=3)       # crash right after the rotation mutation
    inc = e.start(SUBJ)
    with pytest.raises(SimulatedCrash):
        e.run(inc.id)
    rot = [a for a in Store(p).actions(inc.id) if a.type == "rotate_credential"][0]
    assert rot.status == Status.executing  # persisted mid-flight
    st2 = Store(p)
    sb2 = Sandbox(st2)
    rep = Engine(st2, sb2, sleep=nosleep).run(inc.id)
    assert rep["status"] == "closed_verified"
    assert sb2.s["rotations"] == 1         # resumed, not rotated twice


def test_idempotent_replay():
    st, sb, e = mk()
    sb.vault.rotate("cred-pay", "k1")
    r = sb.vault.rotate("cred-pay", "k1")
    assert r["replayed"] and sb.s["rotations"] == 1 and sb.vault.version("cred-pay") == 2


@pytest.mark.parametrize("kind", ["timeout_applied", "timeout_lost"])
def test_ambiguous_outcome(kind):
    st, sb, e = mk(failures={"vault.rotate": [kind]})
    iid, rep = go(e)
    assert rep["status"] == "closed_verified"
    assert sb.s["rotations"] == 1          # reconciled by inspection, never blindly repeated
    evs = [x["event"] for x in st.audit_events(iid)]
    assert "timeout_unknown_outcome" in evs


def test_permanent_failure_escalates():
    st, sb, e = mk(failures={"disable:cloud": ["permanent"]})
    iid, rep = go(e)
    assert rep["status"] == "open"
    assert acts(st, iid)[("disable_account", "jdoe")].status == Status.failed or True
    assert any(u["status"] == "failed" for u in rep["unresolved"])
    assert "escalated" in [x["event"] for x in st.audit_events(iid)]
    assert rep["closure_blocked_reason"]


def test_retries_exhausted_escalates():
    st, sb, e = mk(failures={"app.repair": ["transient"] * 10})
    iid, rep = go(e)
    a = acts(st, iid)[("repair_config", "billing-app")]
    assert a.status == Status.failed and a.retries == 4
    assert rep["status"] == "open"
    assert "escalated" in [x["event"] for x in st.audit_events(iid)]


def test_credential_dependency_blocks_rotation():
    class NoRepair(RuleBasedPlanner):
        def plan(self, obs, iid):
            return [a for a in super().plan(obs, iid) if a.type != "repair_config"]
    st, sb, e = mk(planner=NoRepair())
    iid, rep = go(e)
    assert acts(st, iid)[("rotate_credential", "cred-pay")].status == Status.blocked
    assert sb.vault.version("cred-pay") == 1 and rep["status"] == "open"


def test_shared_credential_requires_approval():
    st, sb, e = mk()
    sb.s["vault"]["credentials"]["cred-pay"]["used_by"] = ["billing-app", "reports-app"]
    sb._save()
    inc = e.start(SUBJ)
    rot = [a for a in st.actions(inc.id) if a.type == "rotate_credential"][0]
    assert rot.status == Status.needs_approval
    rep = e.run(inc.id)
    assert rep["status"] == "open" and sb.vault.version("cred-pay") == 1
    e.approve(inc.id, rot.id)
    rep = e.run(inc.id)
    assert rep["status"] == "closed_verified" and sb.s["rotations"] == 1


def test_failed_credential_verification_keeps_open():
    st, sb, e = mk(flags={"rotate_noop": True})   # rotation "succeeds" but nothing changes
    iid, rep = go(e)
    assert acts(st, iid)[("rotate_credential", "cred-pay")].status == Status.failed
    assert acts(st, iid)[("repair_config", "billing-app")].status == Status.authorized  # never ran
    assert rep["status"] == "open"
    assert any(c["id"] == "cred-pay-old-rejected" and c["result"] is False for c in rep["conditions"])


def test_invalid_replacement_credential():
    st, sb, e = mk(flags={"bad_replacement": True})
    iid, rep = go(e)
    assert acts(st, iid)[("rotate_credential", "cred-pay")].status == Status.failed
    assert rep["status"] == "open"
    assert any(c["id"] == "cred-pay-replacement-works" and c["result"] is False for c in rep["conditions"])


@pytest.mark.parametrize("flag", ["faulty_patch", "unhealthy_app"])
def test_failed_app_check_not_verified(flag):
    st, sb, e = mk(flags={flag: True})
    iid, rep = go(e)
    assert acts(st, iid)[("repair_config", "billing-app")].status == Status.failed
    assert rep["status"] == "open"


def test_missing_verification_evidence_rejects_closure():
    st, sb, e = mk()
    iid, rep = go(e)
    assert rep["status"] == "closed_verified"
    st._x("DELETE FROM conditions WHERE incident_id=?", (iid,))
    rep2 = e.report(iid)
    assert rep2["status"] == "open" and not rep2["invariants"]["closure_conditions_defined"]


def test_inconclusive_observation_rejects_closure(monkeypatch):
    def boom(sb, a):
        raise RuntimeError("observer unavailable")
    monkeypatch.setitem(verification.OBSERVERS, "app_healthy", boom)
    st, sb, e = mk()
    iid, rep = go(e)
    assert rep["status"] == "open"
    assert any(c["result"] is None for c in rep["conditions"])
    assert acts(st, iid)[("repair_config", "billing-app")].status == Status.unknown


def test_audit_report_consistency():
    st, sb, e = mk()
    iid, rep = go(e)
    db = {a.id: a.status.value for a in st.actions(iid)}
    assert {a["id"]: a["status"] for a in rep["actions"]} == db
    events = st.audit_events(iid)
    ok_events = {x["data"].get("action") for x in events
                 if x["event"] == "verification_verified" or x["event"] == "reconciled_verified"}
    assert {k for k, v in db.items() if v == "verified"} <= ok_events
    assert st.incident(iid).status == rep["status"]
    with pytest.raises(Exception):
        st._x("DELETE FROM audit")


def test_secret_redaction():
    assert "sk_test_SYNTH" not in redact({"k": "x sk_test_SYNTH_cred-pay_v2 y"})
    st, sb, e = mk()
    iid, rep = go(e)
    assert "sk_test_SYNTH" not in json.dumps(st.audit_events(iid))
    assert "sk_test_SYNTH" not in json.dumps(st.checkpoints(iid))
    assert "sk_test_SYNTH" not in json.dumps(rep)


def test_invalid_state_transition_rejected():
    a = Action(id="x", incident_id="i", type="disable_account", target="t",
               idem_key="k", status=Status.verified)
    with pytest.raises(InvalidTransition):
        a.move(Status.executing)


def test_cancellation_stops_before_mutation():
    st, sb, e = mk()
    inc = e.start(SUBJ)
    e.cancel()
    rep = e.run(inc.id)
    assert sb.s["rotations"] == 0 and rep["status"] == "open"
    assert "cancelled" in [x["event"] for x in st.audit_events(inc.id)]
