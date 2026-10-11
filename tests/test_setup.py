"""Situations described by whoever is using Rook, rather than ones written in advance.

The point of these is that a judge can invent a day nobody scripted and watch Rook work it out.
The point of the bounds is that describing a situation can never become a way to ask the service
for something it has no data for.
"""
import json

import pytest
from fastapi.testclient import TestClient
from rook.api import DEMO_TOKENS, create_app
from rook.domain import Principal
from rook.engine import Engine, evidence_pack
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


# ---------------------------------------------------------------- a clinic in its own words

OWN = {"organisation": "Riverside Family Practice", "we_do": "Two GP surgeries in Leeds",
       "person_away": "Dr Kofi Mensah", "colleagues": ["Dr Ruth Adeyemi", "Dr Tom Hale"],
       "people_booked_in": 4, "cover_slots": 4}


def test_the_names_a_clinic_types_are_the_names_it_reads_back():
    """Nothing the sandbox invented should survive into the output of somebody who named themselves."""
    st, sb, rep = run(OWN)
    text = json.dumps(rep) + evidence_pack(rep, st.audit_events(rep["incident"]["id"]), st.verify_chain())
    assert rep["status"] == "closed_verified"
    assert "Dr Kofi Mensah is off sick" in rep["incident"]["title"]
    assert "Riverside Family Practice" in text and "Two GP surgeries in Leeds" in text
    for typed in ("Dr Kofi Mensah", "Dr Ruth Adeyemi"):
        assert typed in text
    for invented in ("Ada Okafor", "Jonas Bauer", "Awa Ndiaye", "northside"):
        assert invented not in text, invented


def test_naming_the_organisation_does_not_loosen_who_owns_what():
    """The name is only a name: care actions are still scoped to it, and the scope still has to match."""
    st, sb, rep = run(OWN)
    assert rep["incident"]["subject"] == "Riverside Family Practice"
    assert all(a["policy"]["rule"] != "R2-ownership" for a in rep["actions"])
    assert sb.records.scope() == "Riverside Family Practice"
    plain = Sandbox(Store(":memory:"), scenario="cover_clean")
    assert plain.records.scope() == "clinic:northside"      # unnamed organisations are unchanged


def test_what_staff_reported_is_kept_in_their_words_and_proved():
    said = "Dr Mensah called in sick. Full list this morning and nobody has told the patients."
    with TestClient(app()) as c:
        made = c.post("/api/incidents", headers=H,
                      json={"scenario": "cover_clean", "reported": said, "setup": OWN}).json()
        rep = c.get(f"/api/incidents/{made['id']}", headers=H).json()["report"]
        assert rep["incident"]["reported"] == said
        assert rep["incident"]["organisation"] == {"name": OWN["organisation"], "about": OWN["we_do"]}
        pack = c.get(f"/api/incidents/{made['id']}/evidence", headers=H).text
        assert said in pack
        assert "- Organisation: Riverside Family Practice -- Two GP surgeries in Leeds" in pack


def test_a_name_is_only_ever_a_name():
    """Typed text is bounded and plain, so it cannot carry markup or control characters anywhere."""
    with TestClient(app()) as c:
        for bad in ({"organisation": "<script>alert(1)</script>"}, {"organisation": "   "},
                    {"organisation": "x" * 61}, {"we_do": "y" * 141}, {"person_away": "a\x00b"},
                    {"colleagues": ["a", "b", "c"]}, {"colleagues": [""]}, {"organisation": "back`tick"}):
            r = c.post("/api/incidents", headers=H, json={"scenario": "cover_clean", "setup": bad})
            assert r.status_code == 422, (bad, r.status_code)
        for bad in ("<b>hi</b>", "x" * 301):
            r = c.post("/api/incidents", headers=H, json={"scenario": "cover_clean", "reported": bad})
            assert r.status_code == 422, bad


def test_a_business_that_is_not_a_clinic_gets_its_own_words_too():
    """The same fields on an infrastructure incident: the person who left is whoever they say."""
    with TestClient(app()) as c:
        made = c.post("/api/incidents", headers=H, json={
            "scenario": "clean",
            "setup": {"organisation": "Lakeside Logistics", "person_away": "Marcus Ngata"}}).json()
        assert "Marcus Ngata" in made["title"]
        rep = c.get(f"/api/incidents/{made['id']}", headers=H).json()["report"]
        assert "Marcus Ngata" in rep["incident"]["findings"][0]["text"]
        assert "Jordan Doe" not in json.dumps(rep)


def test_an_organisation_names_its_own_people_without_naming_their_authority():
    """The names reach the record. The right to approve still comes from the token, not the body."""
    named = dict(OWN, who_reports="Grace Boateng", who_approves="Dr Amina Yusuf")
    with TestClient(app()) as c:
        made = c.post("/api/incidents", headers=H, json={"scenario": "cover_clean", "setup": named}).json()
        rep = c.get(f"/api/incidents/{made['id']}", headers=H).json()["report"]
        assert rep["incident"]["organisation"]["who_approves"] == "Dr Amina Yusuf"
        pack = c.get(f"/api/incidents/{made['id']}/evidence", headers=H).text
        assert "- Approves them: Dr Amina Yusuf" in pack
        # The analyst named itself the approver. It still cannot approve anything.
        a = next(a for a in rep["actions"] if a["status"] == "needs_approval")
        r = c.post(f"/api/incidents/{made['id']}/actions/{a['id']}/approve", headers=H, json={})
        assert r.status_code == 403
