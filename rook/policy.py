"""Deterministic, model-independent authorization. Fails closed.

Rook runs as a least-privilege service principal: it may only perform the action types in
ALLOWED, only against the incident subject's own resources, and irreversible actions need a
human approver from the incident's organisation. Policy is evaluated when the plan is made
and again immediately before each action executes, against live state.
"""

ROOK_PRINCIPAL = "svc-rook"

ALLOWED = {
    "disable_account": {"github", "cloud", "pm"},
    "issue_replacement": {"vault"},
    "update_dependent": {"app", "cloud"},
    "revoke_credential": {"vault"},
}
NEEDS_APPROVAL = {"revoke_credential"}     # irreversible and production-affecting


def owner_of(sb, a):
    p = a.params
    try:
        if a.type == "disable_account":
            return sb.account_service(p["service"]).owner(a.target)
        if a.type in ("issue_replacement", "revoke_credential"):
            return sb.vault.owner(a.target)
        if a.type == "update_dependent":
            return sb.vault.owner(p["cred_id"])
    except KeyError:
        return None


def decide(a, inc, sb, plan, approval=None):
    """Returns (authorized | needs_approval | blocked, reason, rule)."""
    if a.type not in ALLOWED or a.params.get("service") not in ALLOWED[a.type]:
        return "blocked", "This action or service is outside what Rook is allowed to do.", "R1-allowlist"
    owner = owner_of(sb, a)
    if owner is None:
        return "blocked", "Rook could not confirm who owns this resource, so it will not touch it.", "R2-ownership"
    if owner != inc.subject:
        return "blocked", f"This resource belongs to {owner}, not to {inc.subject}.", "R2-ownership"

    if a.type == "update_dependent":
        live = sb.dependents_of_fp(a.params["old_fp"])
        if a.target not in live and not _already_moved(sb, a):
            return "blocked", f"{a.target} does not use this credential.", "R3-dependency"
    if a.type == "revoke_credential":
        live = set(sb.dependents_of_fp(a.params["old_fp"]))
        covered = {x.target for x in plan if x.type == "update_dependent"
                   and x.params.get("cred_id") == a.target and x.status.value != "blocked"}
        if live - covered:
            return ("blocked", "Revoking now would break " + ", ".join(sorted(live - covered))
                    + ", which still use the old key and have no update step.", "R4-safe-order")
        if a.params.get("version") == sb.vault.latest(a.target)["v"]:
            pending = [x for x in plan if x.type == "issue_replacement" and x.target == a.target
                       and x.status.value not in ("blocked", "failed", "verified")]
            if not pending:
                return "blocked", "Refusing to revoke the only working version of this key.", "R4-safe-order"

    if a.type in NEEDS_APPROVAL:
        if approval is None:
            return ("needs_approval", "Revoking a key cannot be undone, so a person with approver "
                    "rights must confirm it.", "R5-approval")
        if "approver" not in approval.get("roles", []) or approval.get("org") != inc.org:
            return "blocked", "The approval did not come from an approver in this organisation.", "R5-approval"
        return "authorized", f"Allowed by policy and approved by {approval['by']}.", "R5-approval"
    return "authorized", "Allowed by policy: in scope, owned by the subject, reversible.", "R0-default"


def _already_moved(sb, a):
    cur = sb.vault.latest(a.params["cred_id"])
    return sb.dependent_config_fp(a.target) not in (None, a.params["old_fp"]) and cur["v"] > a.params["old_version"]
