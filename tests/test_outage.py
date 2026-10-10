"""Service outage playbook: bad deploy -> pause pipeline -> roll back -> verify -> resume with the bad revision blocked."""
import pytest
from fastapi.testclient import TestClient
from rook.api import DEMO_TOKENS, create_app
from rook.domain import Principal
from rook.engine import Engine, make_action
from rook.playbooks import Outage, PLAYBOOKS
from rook.sandbox import Sandbox
from rook.store import Store

nosleep = lambda s: None
APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])


def mk(scenario="outage_clean", failures=None, flags=None, **kw):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario, failures=failures, flags=flags)
    return st, sb, Engine(st, sb, sleep=nosleep, **kw)


def by_type(rep):
    return {a["type"]: a for a in rep["actions"]}


def events(st, iid):
    return [x["event"] for x in st.audit_events(iid)]


def test_playbooks_registered():
    assert set(PLAYBOOKS) == {"offboarding", "outage"}


def test_investigation_finds_bad_deploy_and_trap():
    st, sb, e = mk()
    inc = e.start(scenario="outage_clean")
    assert inc.playbook == "outage" and inc.subject == "cloud:checkout-api"     # found from the open alert
    rel = {r["rel"]: r for r in inc.relationships}
    assert rel["deploy"]["revision"] == 42 and rel["deploy"]["minutes_before_alert"] == 1
    assert rel["deploy"]["changed"] == {"DB_HOST": ["db-primary", "db-replica-old"]}
    assert rel["known_good"]["revision"] == 41
    assert rel["pipeline"]["auto_deploy"] and rel["pipeline"]["desired"] == 42
    assert any(r["rel"] == "downstream" and r["caller"] == "app:storefront" for r in inc.relationships)
    text = " ".join(f["text"] for f in inc.findings)
    assert "decommissioned" in text and "overwritten" in text
    assert [a.type for a in st.actions(inc.id)] == ["pause_pipeline", "rollback_service", "resume_pipeline"]
    assert "closure_conditions_defined" in events(st, inc.id)
    assert all(c.result is None for c in st.conditions(inc.id))


def test_clean_outage_closes_with_evidence():
    st, sb, e = mk()
    inc = e.start(scenario="outage_clean")
    assert not sb.cloud.service_healthy("checkout-api")
    rep = e.run(inc.id)
    assert rep["status"] == "closed_verified"
    assert all(c["result"] is True for c in rep["conditions"]) and len(rep["conditions"]) == 7
    assert sb.cloud.deployment("checkout-api")["current"] == 41
    p = sb.cloud.pipeline("checkout-api")
    assert p["auto_deploy"] and p["blocked"] == [42] and p["desired"] == 41
    assert rep["metrics"]["seconds_to_contain"] is not None and rep["metrics"]["contain_label"] == "Service restored after"
    assert any("blocked from redeploying" in f for f in rep["follow_ups"])
    assert sb.pm.tickets()[rep["incident"]["ticket"]]["status"] == "done"


def test_ambiguous_rollback_is_reconciled_not_resent():
    st, sb, e = mk("outage")
    inc = e.start(scenario="outage")
    rep = e.run(inc.id)
    assert rep["status"] == "closed_verified"
    rb = by_type(rep)["rollback_service"]
    assert rb["retries"] == 1
    ev = events(st, inc.id)
    assert "timeout_failure" in ev and "reconciled_verified" in ev
    assert [c["outcome"] for c in rep["tool_calls"] if c["action"] == rb["id"]] == ["timeout"]   # never re-sent


def test_wrong_cause_escalates_and_keeps_pipeline_paused():
    st, sb, e = mk("outage_wrong_cause")
    inc = e.start(scenario="outage_wrong_cause")
    rep = e.run(inc.id)
    a = by_type(rep)
    assert rep["status"] == "escalated"
    assert a["rollback_service"]["status"] == "failed" and a["resume_pipeline"]["status"] == "blocked"
    assert not sb.cloud.pipeline("checkout-api")["auto_deploy"]       # not resumed into a broken state
    assert any("not the whole cause" in f for f in rep["follow_ups"])
    assert any("still paused on purpose" in f for f in rep["follow_ups"])


def test_rollback_api_down_bounded_then_escalated():
    st, sb, e = mk("outage_rollback_down")
    inc = e.start(scenario="outage_rollback_down")
    rep = e.run(inc.id)
    rb = by_type(rep)["rollback_service"]
    assert rep["status"] == "escalated" and rb["status"] == "failed" and rb["retries"] == 4
    assert sb.cloud.deployment("checkout-api")["current"] == 42


def test_pipeline_redeploys_over_unpaused_rollback():
    st, sb, e = mk()
    res = sb.cloud.rollback("checkout-api", 41, "manual-1")
    assert res["pipeline_redeployed"] == 42 and sb.cloud.deployment("checkout-api")["current"] == 42


class NoPause(Outage):
    def plan(self, rel, iid):
        return [a for a in super().plan(rel, iid) if a.type != "pause_pipeline"]


def test_policy_blocks_rollback_without_pause():
    st, sb, e = mk()
    e.planner = NoPause()
    inc = e.start(scenario="outage_clean")
    rb = next(a for a in st.actions(inc.id) if a.type == "rollback_service")
    assert rb.status.value == "blocked" and rb.policy["rule"] == "R4-safe-order"
    rep = e.run(inc.id)
    assert rep["status"] == "escalated" and sb.cloud.deployment("checkout-api")["current"] == 42


def test_rollback_to_unproven_revision_needs_approval():
    from rook import policy
    st, sb, e = mk()
    sb.s["cloud"]["deployments"]["checkout-api"]["revisions"]["40"] = {
        "env": {"DB_HOST": "db-primary"}, "deployed_at": "2026-10-01T00:00:00Z", "deployed_by": "x",
        "commit": "aaa", "message": "", "healthy_minutes": 10}
    inc = e.start(scenario="outage_clean")
    plan = st.actions(inc.id)
    rb = next(a for a in plan if a.type == "rollback_service")
    assert rb.policy["rule"] == "R8-known-good" and rb.status.value == "authorized"     # 41 has a track record
    rb.params["to_revision"] = 40
    assert policy.decide(rb, inc, sb, plan)[0] == "needs_approval"
    ok = {"by": "u-approver", "roles": ["approver"], "org": "acme"}
    assert policy.decide(rb, inc, sb, plan, approval=ok)[0] == "authorized"
    assert policy.decide(rb, inc, sb, plan, approval={**ok, "org": "globex"})[0] == "blocked"


def test_resume_blocked_while_bad_revision_runs():
    st, sb, e = mk()
    inc = e.start(scenario="outage_clean")
    res = next(a for a in st.actions(inc.id) if a.type == "resume_pipeline")
    from rook import policy
    rb = next(a for a in st.actions(inc.id) if a.type == "rollback_service")
    rb.status = rb.status.__class__("failed")
    d, _, rule = policy.decide(res, inc, sb, [rb, res])
    assert d == "blocked" and rule == "R4-safe-order"


def test_outage_over_http(tmp_path):
    app = create_app(db_path=str(tmp_path / "api.db"), tokens=DEMO_TOKENS, step_delay=0, background=False)
    H = {"Authorization": "Bearer demo-analyst-token"}
    with TestClient(app) as c:
        sc = {s["name"]: s["playbook"] for s in c.get("/api/scenarios", headers=H).json()}
        assert sc["outage"] == "outage" and sc["signature"] == "offboarding"
        assert {p["key"] for p in c.get("/api/playbooks", headers=H).json()} == {"offboarding", "outage"}
        iid = c.post("/api/incidents", json={"scenario": "outage"}, headers=H).json()["id"]
        assert c.post(f"/api/incidents/{iid}/run", headers=H).status_code == 202
        body = c.get(f"/api/incidents/{iid}", headers=H).json()
        assert body["report"]["status"] == "closed_verified" and body["report"]["playbook"]["key"] == "outage"
        assert c.get("/api/incidents", headers=H).json()[0]["playbook"] == "outage"
        md = c.get(f"/api/incidents/{iid}/evidence", headers=H).text
        assert "Service outage" in md and "Service restored after" in md
