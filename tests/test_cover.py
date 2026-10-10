"""A doctor calls in sick and a day of appointments has to be moved.

This is the shape of work the product is for: nothing medical, all coordination, and a point in
the middle where a person has to say yes before patients are contacted. The rule worth testing
hardest is the one about not moving someone you cannot tell.
"""
import pytest
from rook.domain import Principal
from rook.engine import Engine
from rook.sandbox import Sandbox
from rook.store import Store

APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])


def run(scenario, approve=True):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario)
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario=scenario)
    rep = e.run(inc.id)
    for _ in range(30):
        pending = [a for a in st.actions(inc.id) if a.status.value == "needs_approval"]
        if not pending or not approve:
            break
        for a in pending:
            e.approve(inc.id, a.id, APPROVER)
        rep = e.run(inc.id)
    return st, sb, e, inc.id, e.finalize(inc.id)


def counts(rep, kind):
    return sum(1 for a in rep["actions"] if a["type"] == kind and a["status"] == "verified")


def test_the_whole_list_is_moved_told_and_checked():
    st, sb, e, iid, rep = run("cover_clean")
    assert rep["status"] == "closed_verified"
    assert counts(rep, "move_appointment") == 12 and counts(rep, "contact_patient") == 12
    assert all(c["result"] is True for c in rep["conditions"])
    # the appointment book itself agrees
    assert sb.schedule.booked_with("clin-okafor") == {}
    assert sb.schedule.double_booked() == []


def test_nobody_is_put_into_a_slot_that_is_already_taken():
    st, sb, e, iid, rep = run("cover_clean")
    times = [(a["doctor"], a["at"]) for a in sb.schedule.appointments().values() if a["status"] == "booked"]
    assert len(times) == len(set(times))
    assert any(c["id"] == "no-double-booking" and c["result"] is True for c in rep["conditions"])


def test_a_failed_move_is_reconciled_rather_than_repeated():
    st, sb, e, iid, rep = run("cover")
    assert rep["status"] == "closed_verified"
    assert rep["metrics"]["retries"] == 1
    assert sb.schedule.double_booked() == []          # the retry did not move anyone twice
    evs = [x["event"] for x in st.audit_events(iid)]
    assert "transient_failure" in evs


def test_patients_are_not_contacted_until_a_person_approves():
    st, sb, e, iid, rep = run("cover_clean", approve=False)
    waiting = [a for a in st.actions(iid) if a.type == "contact_patient"]
    assert waiting and any(a.status.value == "needs_approval" for a in waiting)
    assert sb.outreach.messages("pat-01") == []


def test_rook_will_not_move_someone_it_cannot_tell():
    """Sofia Rossi's number is out of date. Moving her means she arrives at a time that is gone."""
    st, sb, e, iid, rep = run("cover_unreachable")
    assert rep["status"] == "escalated"
    assert counts(rep, "move_appointment") == 11       # everyone except her
    moved = {a["target"] for a in rep["actions"] if a["type"] == "move_appointment"}
    assert "ap-05" not in moved
    assert sb.schedule.appointment("ap-05")["doctor"] == "clin-okafor"   # left exactly where it was
    declined = [r for r in rep["refusals"] if r["kind"] == "declined"]
    assert any("Sofia Rossi" in r["what"] for r in declined)
    assert any("Sofia Rossi" in f for f in rep["follow_ups"])


def test_when_there_are_not_enough_slots_the_rest_stay_open_for_staff():
    st, sb, e, iid, rep = run("cover_short")
    assert rep["status"] == "escalated"
    assert counts(rep, "move_appointment") == 4
    assert len(sb.schedule.booked_with("clin-okafor")) == 8
    unmet = [c["id"] for c in rep["conditions"] if c["result"] is not True]
    assert "session-cleared" in unmet
    assert len([r for r in rep["refusals"] if r["kind"] == "declined"]) == 8
    # the people left behind are named, so reception knows who to phone
    assert any("still booked with a doctor who is not coming in" in f for f in rep["follow_ups"])


def test_one_patients_appointment_cannot_be_changed_under_another_patients_name():
    from rook import policy
    st = Store(":memory:")
    sb = Sandbox(st, scenario="cover_clean")
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario="cover_clean")
    a = next(x for x in st.actions(inc.id) if x.type == "move_appointment")
    a.params = dict(a.params, patient="pat-09")
    decision, reason, rule = policy.decide(a, inc, sb, [a])
    assert decision == "blocked" and rule == "R10-patient-match"
