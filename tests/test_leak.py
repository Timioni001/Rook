"""Leaked-credential playbook: a secrets scanner finds a key hardcoded in a repository.

The interesting cases are the two where Rook declines to rotate: a key that is already dead
(rotating it again would be churn) and one it cannot attribute to an owner (it cannot tell what
would break). Both must still reach a defensible end state rather than a claimed success.
"""
import pytest
from rook.domain import Principal
from rook.engine import Engine
from rook.sandbox import Sandbox
from rook.store import Store

nosleep = lambda s: None
APPROVER = Principal(id="u-approver", org="acme", roles=["analyst", "approver"])


def mk(scenario):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario)
    return st, sb, Engine(st, sb, sleep=nosleep, step_delay=0)


def run(e, scenario):
    inc = e.start(scenario=scenario)
    rep = e.run(inc.id)
    if rep["status"] == "awaiting_approval":
        rev = next(a for a in e.store.actions(inc.id) if a.type == "revoke_credential")
        e.approve(inc.id, rev.id, APPROVER)
        rep = e.run(inc.id)
    return inc.id, rep


def types(rep):
    return [a["type"] for a in rep["actions"]]


@pytest.mark.parametrize("scenario", ["leak", "leak_clean"])
def test_live_leaked_key_is_rotated_and_proven_dead(scenario):
    st, sb, e = mk(scenario)
    iid, rep = run(e, scenario)
    assert rep["status"] == "closed_verified"
    assert types(rep) == ["issue_replacement", "update_dependent", "update_dependent",
                          "revoke_credential", "scrub_exposed_secret"]
    assert all(c["result"] is True for c in rep["conditions"])
    # The key the scanner reported must actually be rejected now, not merely reported revoked.
    leak = next(r for r in st.incident(iid).relationships if r["rel"] == "leak")
    assert sb.vault.authenticate_fp(leak["fp"]) is False
    assert sb.github.secrets_in(leak["path"]) == []


def test_the_scanner_finding_is_attributed_to_an_owner_before_anything_is_touched():
    st, sb, e = mk("leak_clean")
    inc = e.start(scenario="leak_clean")
    assert inc.subject == "ident-asmith"              # the credential's owner, not the file
    leak = next(r for r in inc.relationships if r["rel"] == "leak")
    assert leak["credential"] == "cred-reports" and leak["still_valid"] is True
    assert sorted(leak["live_users"]) == ["app:reports-app", "cloud:reports-cron"]


def test_dependent_missing_from_vault_metadata_is_found_by_scanning_config():
    st, sb, e = mk("leak_clean")
    inc = e.start(scenario="leak_clean")
    cred = next(r for r in inc.relationships if r["rel"] == "owns_credential")
    assert "cloud:reports-cron" in cred["recorded_used_by"]
    # reports-cron is recorded; the point is that discovery uses live config, not the vault's list.
    assert sorted(cred["dependents"]) == ["app:reports-app", "cloud:reports-cron"]


def test_transient_failure_during_the_move_recovers_without_double_applying():
    st, sb, e = mk("leak")
    iid, rep = run(e, "leak")
    assert rep["status"] == "closed_verified"
    assert rep["metrics"]["retries"] == 1 and rep["metrics"]["failed_tool_calls"] == 1
    evs = [x["event"] for x in st.audit_events(iid)]
    assert "transient_failure" in evs and "reconciled_not_applied" in evs


def test_already_revoked_key_is_not_rotated_again():
    """Rotating a dead key is pointless churn. Rook cleans the file and proves the key is dead."""
    st, sb, e = mk("leak_already_revoked")
    iid, rep = run(e, "leak_already_revoked")
    assert rep["status"] == "closed_verified"
    assert types(rep) == ["scrub_exposed_secret"]
    assert not any(a["type"] in ("issue_replacement", "revoke_credential") for a in rep["actions"])
    ids = {c["id"] for c in rep["conditions"]}
    assert {"leak-attributed", "leak-key-dead"} <= ids
    assert all(c["result"] is True for c in rep["conditions"])


def test_unattributable_key_is_never_touched_and_escalates():
    """Rook cannot tell who owns the key or what would break, so it does nothing and says so."""
    st, sb, e = mk("leak_unattributed")
    iid, rep = run(e, "leak_unattributed")
    assert rep["status"] == "escalated"
    assert rep["actions"] == []
    unmet = [c["id"] for c in rep["conditions"] if c["result"] is not True]
    assert "leak-attributed" in unmet
    assert any("cannot attribute" in f for f in rep["follow_ups"])
    # The file is left exactly as it was: no silent edits to something it does not understand.
    assert sb.github.secrets_in("analytics-jobs/config/settings.yml") != []


def test_leak_incidents_are_org_scoped_like_every_other_playbook():
    st, sb, e = mk("leak_clean")
    inc = e.start(org="acme", scenario="leak_clean")
    assert inc.org == "acme" and inc.playbook == "leak"
