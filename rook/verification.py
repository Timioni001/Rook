"""Independent verification.

Observers re-read sandbox state through probes (authentication, health, regression, config
fingerprints). They never look at what an adapter call returned, so a mutation that reports
success without changing state fails verification.
"""
import time
from .domain import Condition


def _account_disabled(sb, a):
    st = sb.account_service(a["service"]).status(a["user"])
    return (None if st is None else st == "disabled"), {"observed_status": st}


def _old_rejected(sb, a):
    accepted = sb.vault.authenticate_fp(a["fp"])
    return (not accepted), {"old_fp": a["fp"], "old_key_authenticates": accepted}


def _replacement_works(sb, a):
    latest = sb.vault.version_info(a["cred_id"], sb.vault.latest(a["cred_id"])["v"])
    ok = latest["v"] > a["old_version"] and sb.vault.authenticate_fp(latest["fp"])
    return ok, {"latest_version": latest["v"], "latest_fp": latest["fp"], "replacement_authenticates": ok}


def _dependent_uses_replacement(sb, a):
    cfg = sb.dependent_config_fp(a["dependent"])
    cur = sb.vault.version_info(a["cred_id"], sb.vault.latest(a["cred_id"])["v"])["fp"]
    ok = cfg == cur and cfg != a["old_fp"]
    return ok, {"dependent_config_fp": cfg, "vault_latest_fp": cur}


def _dependent_healthy(sb, a):
    h = sb.health(a["dependent"])
    return h, {"health_check_passed": h}


def _regression_passes(sb, a):
    r = sb.regression(a["dependent"])
    return r, {"regression_suite_passed": r}


def _no_live_dependents_on_old(sb, a):
    deps = sb.dependents_of_fp(a["fp"])
    return (not deps), {"still_configured_with_old_key": deps}


def _secret_removed(sb, a):
    left = [p for p in sb.github.find_secret(a["fp"]) if p == a["path"]]
    return (not left), {"path": a["path"], "key_still_in_file": bool(left)}


OBSERVERS = {
    "secret_removed_from_repo": _secret_removed,
    "account_disabled": _account_disabled,
    "old_credential_rejected": _old_rejected,
    "replacement_works": _replacement_works,
    "dependent_uses_replacement": _dependent_uses_replacement,
    "dependent_healthy": _dependent_healthy,
    "regression_passes": _regression_passes,
    "no_dependents_on_old_key": _no_live_dependents_on_old,
}


def observe(sb, method, args):
    try:
        return OBSERVERS[method](sb, args)
    except Exception as e:                       # missing/unobservable state => inconclusive
        return None, {"error": type(e).__name__}


def build_conditions(rel):
    conds = []
    for r in rel:
        if r["rel"] == "has_account":
            conds.append(Condition(
                id=f"{r['service']}-{r['user']}-disabled",
                description=f"{r['service']} account '{r['user']}' is disabled",
                expected="account status is disabled", method="account_disabled",
                args={"service": r["service"], "user": r["user"]}))
        elif r["rel"] == "owns_credential" and r["status"] == "active":
            c = r["cred"]
            conds.append(Condition(
                id=f"{c}-old-rejected", description=f"The old key {r['fp']} is rejected when used",
                expected="authentication with the old key fails", method="old_credential_rejected",
                args={"fp": r["fp"]}))
            conds.append(Condition(
                id=f"{c}-replacement-works", description=f"A replacement for {c} is issued and accepted",
                expected="newer version exists and authenticates", method="replacement_works",
                args={"cred_id": c, "old_version": r["version"]}))
            conds.append(Condition(
                id=f"{c}-no-dependents-on-old", description="Nothing is still configured with the old key",
                expected="config scan finds no use of the old key", method="no_dependents_on_old_key",
                args={"fp": r["fp"]}))
            for path in r.get("exposed_in", []):
                conds.append(Condition(
                    id=f"repo:{path}-scrubbed", description=f"The leaked key is removed from {path}",
                    expected="file no longer contains the old key", method="secret_removed_from_repo",
                    args={"path": path, "fp": r["fp"]}))
            for dep in r["dependents"]:
                conds.append(Condition(
                    id=f"{dep}-uses-replacement", description=f"{dep} is configured with the replacement key",
                    expected="config fingerprint == vault latest, != old", method="dependent_uses_replacement",
                    args={"dependent": dep, "cred_id": c, "old_fp": r["fp"]}))
                conds.append(Condition(
                    id=f"{dep}-healthy", description=f"{dep} passes its health check",
                    expected="health probe passes", method="dependent_healthy", args={"dependent": dep}))
                conds.append(Condition(
                    id=f"{dep}-regression", description=f"{dep} passes its regression tests",
                    expected="regression suite passes", method="regression_passes", args={"dependent": dep}))
    return conds


def evaluate(sb, conds):
    out = []
    for c in conds:
        ok, ev = observe(sb, c.method, c.args)
        out.append(c.model_copy(update={"result": ok, "evidence": ev, "evaluated_at": time.time()}))
    return out


def _combine(results):
    ev = {}
    for _, e in results:
        ev.update(e)
    oks = [o for o, _ in results]
    if any(o is False for o in oks):
        return False, ev
    if any(o is None for o in oks):
        return None, ev
    return True, ev


def checks_for(a):
    p = a.params
    if a.type == "disable_account":
        return [("account_disabled", {"service": p["service"], "user": a.target})]
    if a.type == "issue_replacement":
        return [("replacement_works", {"cred_id": a.target, "old_version": p["old_version"]})]
    if a.type == "update_dependent":
        return [("dependent_uses_replacement", {"dependent": a.target, "cred_id": p["cred_id"], "old_fp": p["old_fp"]}),
                ("dependent_healthy", {"dependent": a.target})]
    if a.type == "revoke_credential":
        return [("old_credential_rejected", {"fp": p["old_fp"]})]
    if a.type == "scrub_exposed_secret":
        return [("secret_removed_from_repo", {"path": a.target, "fp": p["old_fp"]})]
    return None


def verify_action(sb, a):
    """True = state shows the action took effect; False = it did not; None = cannot tell."""
    checks = checks_for(a)
    if checks is None:
        return None, {"error": "no verifier"}
    return _combine([observe(sb, m, args) for m, args in checks])


def applied(sb, a):
    """Reconciliation probe after an ambiguous outcome: did the mutation land at all?

    Narrower than verify_action: an applied-but-broken change must not be re-sent blindly.
    """
    p = a.params
    try:
        if a.type == "disable_account":
            return sb.account_service(p["service"]).status(a.target) == "disabled"
        if a.type == "issue_replacement":
            return sb.vault.latest(a.target)["v"] > p["old_version"]
        if a.type == "update_dependent":
            return sb.dependent_config_fp(a.target) != p["old_fp"]
        if a.type == "revoke_credential":
            return sb.vault.version_info(p["cred_id"], p["version"])["status"] == "revoked"
        if a.type == "scrub_exposed_secret":
            return a.target not in sb.github.find_secret(p["old_fp"])
    except Exception:
        return None
    return None
