"""A pitch is shut on a Saturday and three matches have to move.

The point of this playbook is that it is the clinic's problem in a place nobody would call a
clinic: the same engine, the same proof, no medical vocabulary anywhere in it. The rules worth
testing hardest are the two refusals: no match is moved that a club cannot be told about, and no
match is left without an official who is actually available.
"""
from rook.domain import Principal
from rook.engine import Engine, evidence_pack
from rook.sandbox import Sandbox
from rook.store import Store

APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])
ANALYST = Principal(id="u-sam", org="acme", roles=["analyst"])


def run(scenario, approve=True):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario)
    e = Engine(st, sb, sleep=lambda s: None, step_delay=0)
    inc = e.start(scenario=scenario)
    e.run(inc.id)
    for _ in range(30):
        pending = [a for a in st.actions(inc.id) if a.status.value == "needs_approval"]
        if not pending or not approve:
            break
        for a in pending:
            e.approve(inc.id, a.id, APPROVER)
        e.run(inc.id)
    return st, sb, e, inc.id, e.finalize(inc.id)


def verified(rep, kind):
    return sum(1 for a in rep["actions"] if a["type"] == kind and a["status"] == "verified")


def test_a_washed_out_morning_is_moved_told_and_checked():
    st, sb, e, iid, rep = run("fixtures_clean")
    assert rep["status"] == "closed_verified"
    assert verified(rep, "move_fixture") == 3 and verified(rep, "tell_teams") == 3
    assert all(c["result"] is True for c in rep["conditions"])
    # the fixture list itself agrees, not just Rook's account of it
    assert sb.league.at_venue("ven-east") == {}
    assert sb.league.clashes() == []
    assert all(sb.league.told(f) for f in sb.league.fixtures())


def test_a_match_whose_referee_is_away_gets_one_who_is_available():
    st, sb, e, iid, rep = run("fixtures_clean")
    assert verified(rep, "assign_official") == 1
    moved = sb.league.fixture("fx-02")
    assert sb.league.official_available(moved["official"])
    assert moved["official"] != "ref-03"


def test_nobody_is_told_a_kick_off_time_before_the_match_has_one():
    """The message depends on the move, and policy says so again just before it is sent."""
    st, sb, e, iid, rep = run("fixtures_clean")
    by_id = {a["id"]: a for a in rep["actions"]}
    for a in rep["actions"]:
        if a["type"] != "tell_teams":
            continue
        moves = [by_id[d] for d in a["depends_on"] if by_id[d]["type"] == "move_fixture"]
        assert moves and all(m["status"] == "verified" for m in moves)


def test_telling_two_clubs_waits_for_a_person():
    st, sb, e, iid, rep = run("fixtures_clean", approve=False)
    waiting = [a for a in rep["actions"] if a["status"] == "needs_approval"]
    assert waiting and all(a["type"] == "tell_teams" for a in waiting)
    assert all(a["policy"]["rule"] == "R5-approval" for a in waiting)
    assert rep["status"] == "awaiting_approval"
    # and nothing went out while it waited
    assert sb.league.messages() == []


def test_an_analyst_cannot_approve_their_own_message():
    st, sb, e, iid, rep = run("fixtures_clean", approve=False)
    a = next(a for a in rep["actions"] if a["status"] == "needs_approval")
    try:
        e.approve(iid, a["id"], ANALYST)
        assert False, "an analyst approved a message to two clubs"
    except PermissionError:
        pass


def test_a_club_that_cannot_be_told_keeps_its_match_where_it_is():
    st, sb, e, iid, rep = run("fixtures_unreachable")
    assert rep["status"] == "escalated"                     # it will not claim a morning it has not fixed
    assert sb.league.fixture("fx-02")["venue"] == "ven-east"
    declined = [r for r in rep["refusals"] if r["kind"] == "declined"]
    assert len(declined) == 1 and "Riverbank" in declined[0]["why"]
    assert any("Riverbank" in f for f in rep["follow_ups"])


def test_a_match_with_no_available_official_is_left_alone():
    st, sb, e, iid, rep = run("fixtures_no_official")
    assert rep["status"] == "escalated"
    assert sb.league.fixture("fx-02")["venue"] == "ven-east"
    assert any("no official is available" in r["why"].lower() for r in rep["refusals"])


def test_one_slot_for_three_matches_moves_one_and_says_so():
    st, sb, e, iid, rep = run("fixtures_short")
    assert verified(rep, "move_fixture") == 1
    assert len([r for r in rep["refusals"] if r["kind"] == "declined"]) == 2
    assert len(sb.league.at_venue("ven-east")) == 2
    assert not any(c["result"] for c in rep["conditions"] if c["id"] == "pitch-cleared")


def test_a_failed_move_is_recovered_without_moving_anything_twice():
    st, sb, e, iid, rep = run("fixtures")
    assert rep["status"] == "closed_verified"
    assert rep["metrics"]["retries"] == 1
    assert sb.league.clashes() == []
    assert len(sb.league.messages()) == 6                   # two clubs per match, each told once


def test_the_evidence_pack_reads_as_a_club_and_not_a_clinic():
    st, sb, e, iid, rep = run("fixtures_clean")
    pack = evidence_pack(rep, st.audit_events(iid), st.verify_chain())
    assert "Fixture duty" in pack and "Harbour Rangers U12" in pack
    for clinical in ("patient", "clinic", "prescription", "referral"):
        assert clinical not in pack.lower(), clinical
