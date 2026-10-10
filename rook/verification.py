"""Independent verification. Observers read sandbox state only, never adapter responses."""
import time
from .domain import Condition


def _account_disabled(sb, a):
    st = sb.account_service(a["service"]).status(a["user"])
    return (None if st is None else st == "disabled"), {"observed_status": st}


def _credential_rejected(sb, a):
    accepted = sb.vault.accepts_fp(a["fp"])
    return (not accepted), {"old_fp": a["fp"], "old_credential_accepted": accepted}


def _replacement_accepted(sb, a):
    ver, acc = sb.vault.version(a["cred_id"]), sb.vault.accepts_current(a["cred_id"])
    return (ver > 1 and acc), {"vault_version": ver, "replacement_accepted": acc}


def _app_uses_replacement(sb, a):
    cfg, cur = sb.apps.config_fp(a["app"]), sb.vault.current_fp(a["cred_id"])
    ok = cfg == cur and cfg != a["old_fp"]
    return ok, {"app_config_fp": cfg, "vault_current_fp": cur}


def _app_healthy(sb, a):
    h = sb.apps.health(a["app"])
    return h, {"health_check_passed": h}


OBSERVERS = {
    "account_disabled": _account_disabled,
    "credential_rejected": _credential_rejected,
    "replacement_accepted": _replacement_accepted,
    "app_uses_replacement": _app_uses_replacement,
    "app_healthy": _app_healthy,
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
                description=f"Account {r['user']} on {r['service']} is disabled",
                expected="status == disabled", method="account_disabled",
                args={"service": r["service"], "user": r["user"]}))
        elif r["rel"] == "owns_credential" and r["status"] == "active":
            c = r["cred"]
            conds.append(Condition(
                id=f"{c}-old-rejected", description=f"Old credential {r['fp']} is rejected",
                expected="old fingerprint not accepted by vault", method="credential_rejected",
                args={"fp": r["fp"]}))
            conds.append(Condition(
                id=f"{c}-replacement-works", description=f"Replacement for {c} is issued and accepted",
                expected="version > 1 and active", method="replacement_accepted",
                args={"cred_id": c}))
            for app in r["used_by"]:
                conds.append(Condition(
                    id=f"{app}-uses-replacement", description=f"{app} is configured with the replacement",
                    expected="app config == vault current, != old", method="app_uses_replacement",
                    args={"app": app, "cred_id": c, "old_fp": r["fp"]}))
                conds.append(Condition(
                    id=f"{app}-healthy", description=f"{app} passes health/regression check",
                    expected="health check passes", method="app_healthy", args={"app": app}))
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


def verify_action(sb, a):
    p = a.params
    if a.type == "disable_account":
        checks = [("account_disabled", {"service": p["service"], "user": a.target})]
    elif a.type == "rotate_credential":
        checks = [("credential_rejected", {"fp": p["old_fp"]}),
                  ("replacement_accepted", {"cred_id": a.target})]
    elif a.type == "repair_config":
        checks = [("app_uses_replacement", {"app": a.target, "cred_id": p["cred_id"], "old_fp": p["old_fp"]}),
                  ("app_healthy", {"app": a.target})]
    else:
        return None, {"error": "no verifier"}
    return _combine([observe(sb, m, args) for m, args in checks])
