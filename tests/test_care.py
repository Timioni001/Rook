"""Care follow-up: things a clinic's record calls done that nobody ever actually completed.

Rook is administrative here. It chases paperwork and people. The tests that matter most are the
ones where it stops: a critical finding belongs to a clinician, and a patient who cannot be
reached means the loop is not closed, whatever the record would like to say.
"""
import pytest
from rook.domain import Principal
from rook.engine import Engine, evidence_pack
from rook.sandbox import Sandbox
from rook.store import Store

APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])
ANALYST = Principal(id="u-analyst", org="acme", roles=["analyst"])


def run(scenario, approve=True):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario)
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario=scenario)
    rep = e.run(inc.id)
    for _ in range(8):
        pending = [a for a in st.actions(inc.id) if a.status.value == "needs_approval"]
        if not pending or not approve:
            break
        for a in pending:
            e.approve(inc.id, a.id, APPROVER)
        rep = e.run(inc.id)
    return st, sb, e, inc.id, e.finalize(inc.id)


def by_order(rep):
    out = {}
    for a in rep["actions"]:
        out.setdefault(a["target"], []).append(a["type"])
    return out


def test_the_sweep_finds_what_the_record_hides():
    """Three of four are marked done in the record and have not happened."""
    st, sb, e, iid, rep = run("referral_clean")
    hs = [r for r in st.incident(iid).relationships if r["rel"] == "follow_up"]
    assert len(hs) == 4
    assert sum(not h["finished"] for h in hs) == 3
    # Each gap was found by asking the system that would know, not by reading the record.
    referral = next(h for h in hs if h["order"] == "ord-7741")
    assert referral["record_status"] == "sent" and referral["received"] is False


def test_every_unfinished_one_is_driven_to_a_verified_finish():
    st, sb, e, iid, rep = run("referral_clean")
    assert rep["status"] == "closed_verified"
    assert all(c["result"] is True for c in rep["conditions"])
    acts = by_order(rep)
    assert acts["ord-7741"] == ["resend_referral", "book_appointment", "contact_patient", "close_loop"]
    assert acts["ord-7742"] == ["notify_clinician", "close_loop"]
    assert acts["ord-7743"] == ["resend_prescription", "contact_patient", "close_loop"]
    # and the real world agrees
    assert sb.booking.received("ord-7741", "cardiology")
    assert sb.booking.appointment_for("pat-alvarez", "cardiology") is not None
    assert sb.pharmacy.has("ord-7743")


def test_the_one_that_really_did_happen_is_left_alone():
    st, sb, e, iid, rep = run("referral_clean")
    assert "ord-7744" not in by_order(rep)
    declined = [r for r in rep["refusals"] if r["kind"] == "declined"]
    assert any("Lucia Rivera" in r["what"] for r in declined)


def test_a_booking_failure_is_reconciled_rather_than_blindly_retried():
    st, sb, e, iid, rep = run("referral")
    assert rep["status"] == "closed_verified"
    assert rep["metrics"]["retries"] == 1
    evs = [x["event"] for x in st.audit_events(iid)]
    assert "transient_failure" in evs and "reconciled_not_applied" in evs
    # one appointment, not two
    appts = [a for a in sb.s["booking"]["appointments"].values() if a["patient"] == "pat-alvarez"]
    assert len(appts) == 1


def test_contacting_a_patient_needs_a_person_to_approve_it():
    st, sb, e, iid, rep = run("referral_clean", approve=False)
    waiting = [a for a in st.actions(iid) if a.type == "contact_patient"]
    assert waiting and all(a.status.value == "needs_approval" for a in waiting)
    assert all(a.policy["rule"] == "R5-approval" for a in waiting)
    assert sb.outreach.messages("pat-alvarez") == []     # nothing was sent


def test_a_critical_finding_is_paged_to_a_clinician_and_nothing_else():
    st, sb, e, iid, rep = run("referral_critical")
    assert rep["status"] == "escalated"
    assert by_order(rep)["ord-7742"] == ["notify_clinician"]
    assert sb.records.notified("ord-7742")
    assert not sb.records.loop_closed("ord-7742")
    declined = [r for r in rep["refusals"] if r["kind"] == "declined"]
    assert any(r["rule"] == "R6-clinical-scope" for r in declined)
    unmet = [c["id"] for c in rep["conditions"] if c["result"] is not True]
    assert "ord-7742-acknowledged" in unmet
    # the other patients' handoffs are still fixed; one escalation does not stall the sweep
    assert sb.booking.appointment_for("pat-alvarez", "cardiology") is not None
    assert sb.pharmacy.has("ord-7743")


def test_an_unreachable_patient_blocks_the_record_from_claiming_closure():
    st, sb, e, iid, rep = run("referral_unreachable")
    assert rep["status"] == "escalated"
    close = next(a for a in rep["actions"] if a["type"] == "close_loop" and a["target"] == "ord-7741")
    assert close["status"] == "blocked" and close["policy"]["rule"] == "R9-truthful-record"
    assert not sb.records.loop_closed("ord-7741")
    unmet = [c["id"] for c in rep["conditions"] if c["result"] is not True]
    assert "ord-7741-patient-told" in unmet and "ord-7741-record-true" in unmet


def test_the_record_can_never_be_marked_closed_while_a_gap_remains():
    """R9 is the rule the whole playbook exists for, so check it directly."""
    from rook import policy
    st = Store(":memory:")
    sb = Sandbox(st, scenario="referral_clean")
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario="referral_clean")
    close = next(a for a in st.actions(inc.id) if a.type == "close_loop" and a.target == "ord-7741")
    # On its own, with nothing else left to run, closing is refused.
    decision, reason, rule = policy.decide(close, inc, sb, [close])
    assert decision == "blocked" and rule == "R9-truthful-record"
    assert "never got the referral" in reason


def test_one_patients_follow_up_cannot_touch_another_patient():
    from rook import policy
    st = Store(":memory:")
    sb = Sandbox(st, scenario="referral_clean")
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario="referral_clean")
    a = next(x for x in st.actions(inc.id) if x.type == "contact_patient")
    a.params = dict(a.params, patient="pat-rivera")      # same clinic, wrong person
    decision, reason, rule = policy.decide(a, inc, sb, [a], approval={"by": "u-approver",
                                                                      "roles": ["approver"], "org": "acme"})
    assert decision == "blocked" and rule == "R10-patient-match"


def test_evidence_pack_speaks_the_clinic_s_language():
    st, sb, e, iid, rep = run("referral_clean")
    md = evidence_pack(rep, st.audit_events(iid), st.verify_chain())
    assert "Care follow-up" in md and "Patient safety" in md
    assert "## Control mapping" in md
