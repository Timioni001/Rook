"""Situations described by whoever is using Rook, rather than ones written in advance.

The point of these is that a judge can invent a day nobody scripted and watch Rook work it out.
The point of the bounds is that describing a situation can never become a way to ask the service
for something it has no data for.
"""
import pytest
from fastapi.testclient import TestClient
from rook.api import DEMO_TOKENS, create_app
from rook.domain import Principal
from rook.engine import Engine
from rook.sandbox import Sandbox
from rook.store import Store

H = {"Authorization": "Bearer demo-analyst-token"}
APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])


def app():
    return create_app(db_path=":memory:", tokens=DEMO_TOKENS, step_delay=0, background=False)


def run(setup, scenario="cover_clean"):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario, setup=setup)
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario=scenario)
    rep = e.run(inc.id)
    for _ in range(30):
        pending = [a for a in st.actions(inc.id) if a.status.value == "needs_approval"]
        if not pending:
            break
        for a in pending:
            e.approve(inc.id, a.id, APPROVER)
        rep = e.run(inc.id)
    return st, sb, e.finalize(inc.id)


def test_the_numbers_a_person_types_reach_the_agent():
    st, sb, rep = run({"people_booked_in": 7, "cover_slots": 2})
    assert "7 appointments" in rep["incident"]["title"]
    rows = [r for r in st.incident(rep["incident"]["id"]).relationships if r["rel"] == "booking"]
    assert len(rows) == 7
    assert sum(1 for a in rep["actions"] if a["type"] == "move_appointment") == 2


def test_an_invented_situation_still_ends_in_a_defensible_verdict():
    """Seven people, two slots, one of them unreachable: one move, six left for reception."""
    st, sb, rep = run({"people_booked_in": 7, "cover_slots": 2, "people_we_cannot_reach": 1})
    assert rep["status"] == "escalated"
    assert sum(1 for a in rep["actions"] if a["type"] == "move_appointment" and a["status"] == "verified") == 1
    assert len(sb.schedule.booked_with("clin-okafor")) == 6
    assert len([r for r in rep["refusals"] if r["kind"] == "declined"]) == 6


def test_no_slots_means_rook_moves_nobody_rather_than_improvising():
    st, sb, rep = run({"cover_slots": 0})
    assert rep["actions"] == []
    assert rep["status"] == "escalated"
    assert len(sb.schedule.booked_with("clin-okafor")) == 12


def test_a_requested_failure_is_recovered_not_double_applied():
    st, sb, rep = run({"people_booked_in": 4, "cover_slots": 4, "one_step_fails": True})
    assert rep["status"] == "closed_verified"
    assert rep["metrics"]["retries"] == 1
    assert sb.schedule.double_booked() == []


def test_finding_nothing_to_do_is_a_real_outcome():
    """Everything the record claims really did happen, so Rook closes it with no actions at all."""
    st, sb, rep = run(None, scenario="referral_all_good")
    assert rep["status"] == "closed_verified"
    assert rep["actions"] == []
    assert all(c["result"] is True for c in rep["conditions"])
    assert any(r["kind"] == "declined" for r in rep["refusals"])


def test_setup_is_bounded_and_closed_to_unknown_fields():
    with TestClient(app()) as c:
        assert c.post("/api/incidents", headers=H,
                      json={"scenario": "cover_clean", "setup": {"people_booked_in": 5}}).status_code == 201
        for bad in ({"people_booked_in": 0}, {"people_booked_in": 9999}, {"cover_slots": -1},
                    {"people_we_cannot_reach": 10 ** 6}, {"drop_everything": True},
                    {"people_booked_in": "lots"}):
            r = c.post("/api/incidents", headers=H, json={"scenario": "cover_clean", "setup": bad})
            assert r.status_code == 422, (bad, r.status_code)


def test_a_described_situation_is_still_org_scoped():
    with TestClient(app()) as c:
        made = c.post("/api/incidents", headers=H,
                      json={"scenario": "cover_clean", "setup": {"people_booked_in": 3}}).json()
        other = {"Authorization": "Bearer demo-other-org-token"}
        assert c.get(f"/api/incidents/{made['id']}", headers=other).status_code == 404


def test_describing_a_situation_needs_the_right_role():
    with TestClient(app()) as c:
        viewer = {"Authorization": "Bearer demo-viewer-token"}
        r = c.post("/api/incidents", headers=viewer,
                   json={"scenario": "cover_clean", "setup": {"people_booked_in": 3}})
        assert r.status_code == 403
