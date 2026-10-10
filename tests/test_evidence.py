"""Refusals, impact metrics and the auditor-facing evidence pack.

The refusals list is the part a buyer reads first: an agent that acts on what it cannot explain is
the dangerous kind, so what Rook declined has to be as legible as what it did.
"""
import pytest
from rook.domain import Principal
from rook.engine import Engine, evidence_pack
from rook.sandbox import Sandbox
from rook.store import Store
from rook.verification import CONTROLS, OBSERVERS, control_for

APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])


def run(scenario):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario)
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario=scenario)
    rep = e.run(inc.id)
    if rep["status"] == "awaiting_approval":
        rev = next(a for a in st.actions(inc.id) if a.type == "revoke_credential")
        e.approve(inc.id, rev.id, APPROVER)
        e.run(inc.id)
    return st, e, inc.id, e.finalize(inc.id)


def test_every_observer_has_a_control_mapping():
    """A closure check with no mapping would silently vanish from the auditor's table."""
    assert set(OBSERVERS) <= set(CONTROLS)


def test_unattributable_key_is_reported_as_a_refusal_not_a_gap():
    st, e, iid, rep = run("leak_unattributed")
    assert rep["status"] == "escalated"
    declined = [r for r in rep["refusals"] if r["kind"] == "declined"]
    assert declined and declined[0]["rule"] == "R2-ownership"
    assert "cannot tell who owns it" in declined[0]["why"]
    assert rep["metrics"]["refusals"] == len(rep["refusals"])


def test_already_dead_key_is_refused_rather_than_rotated():
    st, e, iid, rep = run("leak_already_revoked")
    assert rep["status"] == "closed_verified"
    assert [r["kind"] for r in rep["refusals"]] == ["declined"]
    assert "churn" in rep["refusals"][0]["why"]


def test_ownerless_account_is_a_refusal_on_the_offboarding_playbook():
    st, e, iid, rep = run("signature")
    assert rep["status"] == "closed_verified"
    declined = [r for r in rep["refusals"] if r["kind"] == "declined"]
    assert any("ghost" in r["what"] for r in declined)


def test_impact_metrics_count_real_work_not_invented_minutes():
    st, e, iid, rep = run("leak_clean")
    m = rep["metrics"]
    assert m["independent_checks"] == len(rep["conditions"])
    assert m["manual_steps_replaced"] == len(rep["actions"]) + len(rep["conditions"])
    assert m["systems_touched"] >= 1
    assert m["human_decisions"] == 1          # the revocation needed an approver


def test_evidence_pack_maps_checks_to_controls_and_lists_refusals():
    st, e, iid, rep = run("leak_clean")
    md = evidence_pack(rep, st.audit_events(iid), st.verify_chain())
    assert "## Control mapping" in md and "## What Rook refused to do" in md
    assert "SOC 2 CC6.1" in md and "ISO 27001 A.5.17" in md
    # The mapping is offered as a starting point, never as a claim that an audit would pass.
    assert "not a claim that an audit would pass" in md
    assert "## What this replaced" in md


def test_control_counts_are_per_control_not_per_framework():
    """CC6.1 covers several distinct ISO controls; each row must count only its own checks."""
    st, e, iid, rep = run("leak_clean")
    md = evidence_pack(rep, st.audit_events(iid), st.verify_chain())
    rows = [l for l in md.splitlines() if l.startswith("| SOC 2 CC6.1 |")]
    assert len(rows) >= 2
    totals = [int(r.rstrip(" |").split("/")[-1]) for r in rows]
    assert sum(totals) == sum(1 for c in rep["conditions"] if control_for(c["method"])[0] == "SOC 2 CC6.1")
