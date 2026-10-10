"""Deterministic, model-independent authorization. Fails closed.

Rook runs as a least-privilege service principal: it may only perform the action types in
ALLOWED, only against resources that belong to the incident's subject (the offboarded person, or
the failing service), and irreversible or uncertain actions need a human approver from the
incident's organisation. Policy is evaluated when the plan is made
and again immediately before each action executes, against live state.
"""

ROOK_PRINCIPAL = "svc-rook"

CARE_ACTIONS = {"resend_referral", "book_appointment", "contact_patient", "notify_clinician",
                "close_loop", "resend_prescription", "move_appointment"}

ALLOWED = {
    "disable_account": {"github", "cloud", "pm"},
    "issue_replacement": {"vault"},
    "update_dependent": {"app", "cloud"},
    "revoke_credential": {"vault"},
    "scrub_exposed_secret": {"github"},
    "pause_pipeline": {"cloud"},
    "rollback_service": {"cloud"},
    "resume_pipeline": {"cloud"},
    "resend_referral": {"records"},
    "book_appointment": {"booking"},
    "contact_patient": {"outreach"},
    "notify_clinician": {"records"},
    "close_loop": {"records"},
    "resend_prescription": {"pharmacy"},
    "move_appointment": {"schedule"},
}
KNOWN_GOOD_MINUTES = 60      # a revision must have run healthy this long to be rolled back to unattended
# Revoking a key is irreversible. Contacting a patient reaches a person outside the building and
# cannot be taken back either, so both wait for someone accountable.
NEEDS_APPROVAL = {"revoke_credential", "contact_patient"}


def _care_record(sb, target):
    """A care action points either at something the clinic ordered, or at an appointment."""
    return sb.records.order(target) or sb.schedule.appointment(target)


def owner_of(sb, a):
    p = a.params
    try:
        if a.type == "disable_account":
            return sb.account_service(p["service"]).owner(a.target)
        if a.type in ("issue_replacement", "revoke_credential"):
            return sb.vault.owner(a.target)
        if a.type in ("update_dependent", "scrub_exposed_secret"):
            return sb.vault.owner(p["cred_id"])
        if a.type in ("pause_pipeline", "rollback_service", "resume_pipeline"):
            sb.cloud.deployment(a.target)
            return f"cloud:{a.target}"
        if a.type in CARE_ACTIONS:
            # Scoped to the clinic this incident is about. R10 then pins each action to the patient
            # named on its own record, so one person's care can never be changed under another's.
            return f"clinic:{sb.records.clinic()}" if _care_record(sb, a.target) else None
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

    if a.type == "rollback_service":
        p = sb.cloud.pipeline(a.target)
        paused_in_plan = any(x.type == "pause_pipeline" and x.target == a.target and x.status.value != "blocked"
                             for x in plan)
        if p["auto_deploy"] and p["desired"] != a.params["to_revision"] and not paused_in_plan:
            return ("blocked", f"Auto-deploy would put revision {p['desired']} straight back over the rollback; "
                    "the pipeline has to be paused first.", "R4-safe-order")
        try:
            target = sb.cloud.revision(a.target, a.params["to_revision"])
        except KeyError:
            return "blocked", "That revision does not exist.", "R3-dependency"
        if target["healthy_minutes"] < KNOWN_GOOD_MINUTES:
            if approval is None:
                return ("needs_approval", f"Revision {a.params['to_revision']} has no healthy track record, so a person "
                        "must confirm rolling back to it.", "R8-known-good")
            if "approver" not in approval.get("roles", []) or approval.get("org") != inc.org:
                return "blocked", "The approval did not come from an approver in this organisation.", "R8-known-good"
            return "authorized", f"Approved by {approval['by']}.", "R8-known-good"
        return ("authorized", f"Revision {a.params['to_revision']} ran healthy for {target['healthy_minutes'] // 60} h "
                "before the bad deploy; rolling back to it is reversible.", "R8-known-good")
    if a.type == "resume_pipeline":
        cur = sb.cloud.deployment(a.target)["current"]
        rb = [x for x in plan if x.type == "rollback_service" and x.target == a.target]
        if cur == a.params["block_revision"] and not any(x.status.value not in ("blocked", "failed") for x in rb):
            return ("blocked", f"The service still runs revision {cur}; resuming now would keep the bad change live.",
                    "R4-safe-order")

    if a.type in CARE_ACTIONS:
        o = _care_record(sb, a.target)
        if o is None:
            return "blocked", "That record does not exist.", "R3-dependency"
        if a.params.get("patient") and a.params["patient"] != o["patient"]:
            return ("blocked", "This action names a different patient than the order it belongs to.",
                    "R10-patient-match")
    if a.type == "close_loop":
        # The record's "closed" flag is the thing everyone downstream trusts and nobody re-checks.
        # Rook may only set it when a fresh look at the other systems finds nothing missing. Policy
        # runs again immediately before execution, so at plan time it is enough that the plan still
        # has live steps for this handoff; by the time it runs, the gaps are real or they are gone.
        missing = sb.handoff_gaps(a.target)
        if missing:
            pending = [x for x in plan if x.target == a.target and x.type != "close_loop"
                       and x.status.value not in ("blocked", "failed", "verified")]
            if not pending:
                return ("blocked", "Marking this closed would be false: " + ", ".join(missing) + ".",
                        "R9-truthful-record")

    if a.type in NEEDS_APPROVAL:
        if approval is None:
            why = ("Contacting a patient reaches a real person and cannot be taken back, so someone "
                   "accountable has to confirm it." if a.type == "contact_patient" else
                   "Revoking a key cannot be undone, so a person with approver rights must confirm it.")
            return "needs_approval", why, "R5-approval"
        if "approver" not in approval.get("roles", []) or approval.get("org") != inc.org:
            return "blocked", "The approval did not come from an approver in this organisation.", "R5-approval"
        return "authorized", f"Allowed by policy and approved by {approval['by']}.", "R5-approval"
    return "authorized", "Allowed by policy: in scope, owned by the subject, reversible.", "R0-default"


def may_compensate(sb, a, inc):
    """R7: rolling a dependent back to its previous key is allowed only while that key is still valid
    and the dependent belongs to the incident's credential. It restores a known-good state."""
    if a.type != "update_dependent" or owner_of(sb, a) != inc.subject:
        return False, "Rollback only applies to services of this incident's credential."
    if not sb.vault.authenticate_fp(a.params["old_fp"]):
        return False, "The previous key is no longer valid, so rolling back would not help."
    return True, "Previous key is still valid; restoring the last known-good configuration."


def _already_moved(sb, a):
    cur = sb.vault.latest(a.params["cred_id"])
    return sb.dependent_config_fp(a.target) not in (None, a.params["old_fp"]) and cur["v"] > a.params["old_version"]
