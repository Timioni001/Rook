"""Deterministic, model-independent authorization. Fails closed."""

ALLOWED = {
    "disable_account": {"github", "cloud", "pm"},
    "rotate_credential": {"vault"},
    "repair_config": {"app"},
}


def owner_of(sb, a):
    p = a.params
    try:
        if a.type == "disable_account":
            return sb.account_service(p["service"]).owner(a.target)
        if a.type == "rotate_credential":
            return sb.vault.owner(a.target)
        if a.type == "repair_config":
            return sb.vault.owner(p["cred_id"])
    except KeyError:
        return None


def decide(a, inc, sb, plan, approved=False):
    """Returns (authorized | needs_approval | blocked, reason)."""
    if a.type not in ALLOWED or a.params.get("service") not in ALLOWED[a.type]:
        return "blocked", "action/service outside approved policy"
    owner = owner_of(sb, a)
    if owner is None:
        return "blocked", "ownership cannot be established (fail closed)"
    if owner != inc.subject:
        return "blocked", f"target belongs to {owner}, not incident subject {inc.subject}"
    if a.type == "repair_config":
        if a.target not in sb.vault.used_by(a.params["cred_id"]):
            return "blocked", "app is not a dependent of this credential"
    if a.type == "rotate_credential":
        deps = set(sb.vault.used_by(a.target))
        have = {x.target for x in plan
                if x.type == "repair_config" and x.params.get("cred_id") == a.target}
        if deps - have:
            return "blocked", f"dependent apps without repair step: {sorted(deps - have)}"
        if len(deps) > 1 and not approved:
            return "needs_approval", f"credential shared by {len(deps)} apps (blast radius): human approval required"
    return "authorized", "approved by policy" + (" + human approval" if approved else "")
