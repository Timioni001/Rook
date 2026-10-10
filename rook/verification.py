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


def _service_healthy(sb, a):
    h = sb.cloud.service_healthy(a["service"])
    return h, {"service": a["service"], "health_check_passed": h}


def _error_rate_ok(sb, a):
    r = sb.cloud.error_rate(a["service"])
    return r < a["max"], {"error_rate": r, "threshold": a["max"]}


def _running_known_good(sb, a):
    cur = sb.cloud.deployment(a["service"])["current"]
    return cur != a["bad_revision"] and cur in a["good_revisions"], {"running_revision": cur}


def _caller_healthy(sb, a):
    h = sb.caller_healthy(a["caller"], a["service"])
    return h, {"caller": a["caller"], "healthy": h}


def _synthetic_checkout(sb, a):
    ok = sb.synthetic_checkout(a["service"])
    return ok, {"test_order_placed": ok}


def _pipeline_resumed(sb, a):
    p = sb.cloud.pipeline(a["service"])
    return p["auto_deploy"], {"auto_deploy": p["auto_deploy"]}


def _revision_blocked(sb, a):
    p = sb.cloud.pipeline(a["service"])
    ok = a["revision"] in p["blocked"] and p["desired"] != a["revision"]
    return ok, {"blocked_revisions": p["blocked"], "pipeline_desired": p["desired"]}


# ---------------------------------------------------------------- referral & result follow-up
# Every one of these reads the system that would actually know, which is rarely the system that
# claims the work is done. The record saying "sent" is not evidence that anyone received it.

KIND_LABEL_V = {"referral": "referral", "result": "test result", "prescription": "prescription"}


def _referral_received(sb, a):
    got = sb.booking.received(a["order"], a["specialty"])
    return got, {"specialist_inbox": a["specialty"], "has_referral": got}


def _appointment_booked(sb, a):
    appt = sb.booking.appointment_for(a["patient"], a["specialty"])
    return appt is not None, {"appointment": appt}


def _patient_reached(sb, a):
    """Reached means the patient answered on a channel, not that a message was sent into the void."""
    msgs = sb.outreach.messages(a["patient"])
    return sb.outreach.reached(a["patient"]), {
        "attempts": [{"channel": m["kind"], "delivered": m["delivered"], "responded": m["responded"]} for m in msgs]}


def _clinician_notified(sb, a):
    notes = sb.records.notified(a["order"])
    return bool(notes), {"pages": notes}


def _clinician_acknowledged(sb, a):
    who = sb.records.acknowledged(a["order"])
    return who is not None, {"acknowledged_by": who}


def _loop_closed_in_record(sb, a):
    done = sb.records.loop_closed(a["order"])
    return done, {"loop_closed": done}


def _appointment_moved(sb, a):
    ap = sb.schedule.appointment(a["appointment"])
    ok = bool(ap) and ap["status"] == "booked" and ap["doctor"] != a["from_doctor"]
    return ok, {"now_with": sb.schedule.doctor_name(ap["doctor"]) if ap else None,
                "at": ap["at"] if ap else None}


def _no_double_booking(sb, a):
    clashes = sb.schedule.double_booked()
    return not clashes, {"clashes": clashes}


def _session_cleared(sb, a):
    """Nobody is still booked in with a doctor who is not coming in."""
    left = sb.schedule.booked_with(a["doctor"])
    return not left, {"still_booked": [{"appointment": k, "patient": v["patient"], "at": v["at"]}
                                       for k, v in sorted(left.items())]}


def _prescription_at_pharmacy(sb, a):
    there = sb.pharmacy.has(a["order"])
    return there, {"at_pharmacy": there, "dispensed": sb.pharmacy.dispensed(a["order"])}


def _leak_attributed(sb, a):
    """Can this leaked fingerprint be tied to a credential with a known owner? Rook never acts on
    access it cannot attribute, so this is a closure condition rather than a plan-time guess."""
    cid = sb.vault.find_by_fp(a["fp"])
    owner = sb.vault.owner(cid) if cid else None
    return bool(cid and owner), {"credential": cid, "owner": owner}


OBSERVERS = {
    "service_healthy": _service_healthy,
    "error_rate_below": _error_rate_ok,
    "running_known_good": _running_known_good,
    "caller_healthy": _caller_healthy,
    "synthetic_checkout_passes": _synthetic_checkout,
    "pipeline_resumed": _pipeline_resumed,
    "bad_revision_blocked": _revision_blocked,
    "secret_removed_from_repo": _secret_removed,
    "account_disabled": _account_disabled,
    "old_credential_rejected": _old_rejected,
    "replacement_works": _replacement_works,
    "dependent_uses_replacement": _dependent_uses_replacement,
    "dependent_healthy": _dependent_healthy,
    "regression_passes": _regression_passes,
    "no_dependents_on_old_key": _no_live_dependents_on_old,
    "leak_attributed": _leak_attributed,
    "referral_received": _referral_received,
    "prescription_at_pharmacy": _prescription_at_pharmacy,
    "appointment_moved": _appointment_moved,
    "no_double_booking": _no_double_booking,
    "session_cleared": _session_cleared,
    "appointment_booked": _appointment_booked,
    "patient_reached": _patient_reached,
    "clinician_notified": _clinician_notified,
    "clinician_acknowledged": _clinician_acknowledged,
    "loop_closed_in_record": _loop_closed_in_record,
}


OBSERVERS["pipeline_paused"] = lambda sb, a: (
    not sb.cloud.pipeline(a["service"])["auto_deploy"], {"auto_deploy": sb.cloud.pipeline(a["service"])["auto_deploy"]})


def observe(sb, method, args):
    try:
        return OBSERVERS[method](sb, args)
    except Exception as e:                       # missing/unobservable state => inconclusive
        return None, {"error": type(e).__name__}


def outage_conditions(rel):
    """Closure for a service outage: healthy on a known-good revision, callers fine, nothing left frozen."""
    st = next(r for r in rel if r["rel"] == "service_state")
    svc = st["service"]
    dep = next((r for r in rel if r["rel"] == "deploy"), None)
    good = [r["revision"] for r in rel if r["rel"] == "known_good"]
    conds = [
        Condition(id=f"{svc}-healthy", description=f"{svc} passes its health check", expected="health probe passes",
                  method="service_healthy", args={"service": svc}),
        Condition(id=f"{svc}-error-rate", description=f"{svc} error rate is back under 1%",
                  expected="error rate < 0.01", method="error_rate_below", args={"service": svc, "max": 0.01}),
    ]
    if dep:
        conds.append(Condition(id=f"{svc}-known-good", description=f"{svc} runs a known-good revision, not {dep['revision']}",
                               expected=f"running revision in {good}", method="running_known_good",
                               args={"service": svc, "bad_revision": dep["revision"], "good_revisions": good}))
    for r in rel:
        if r["rel"] == "downstream":
            conds.append(Condition(id=f"{r['caller']}-healthy", description=f"{r['caller']}, which calls {svc}, is healthy",
                                   expected="caller health probe passes", method="caller_healthy",
                                   args={"caller": r["caller"], "service": svc}))
    conds.append(Condition(id=f"{svc}-synthetic-order", description="A synthetic test order goes through end to end",
                           expected="test order placed", method="synthetic_checkout_passes", args={"service": svc}))
    if any(r["rel"] == "pipeline" for r in rel):
        conds.append(Condition(id=f"{svc}-pipeline-resumed", description="The deploy pipeline is running again, not left frozen",
                               expected="auto-deploy on", method="pipeline_resumed", args={"service": svc}))
        if dep:
            conds.append(Condition(id=f"{svc}-rev{dep['revision']}-blocked",
                                   description=f"Revision {dep['revision']} is blocked from redeploying",
                                   expected="revision in pipeline blocklist and not desired",
                                   method="bad_revision_blocked", args={"service": svc, "revision": dep["revision"]}))
    return conds


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


# Indicative control mapping for the evidence pack. Each closure check is an independently observed
# fact, which is what an auditor samples for these controls. The mapping is a starting point to
# confirm with your own auditor, not an assertion that an audit would pass.
CONTROLS = {
    "account_disabled": ("SOC 2 CC6.2", "ISO 27001 A.5.18", "Access is removed when it is no longer required"),
    "old_credential_rejected": ("SOC 2 CC6.1", "ISO 27001 A.5.17", "Revoked authentication information is rejected"),
    "replacement_works": ("SOC 2 CC6.1", "ISO 27001 A.5.17", "Replacement authentication information is in place"),
    "no_dependents_on_old_key": ("SOC 2 CC6.1", "ISO 27001 A.5.17", "No system still authenticates with the old key"),
    "secret_removed_from_repo": ("SOC 2 CC6.1", "ISO 27001 A.8.28", "Credentials are not held in source code"),
    "leak_attributed": ("SOC 2 CC6.1", "ISO 27001 A.5.16", "Every credential has an identified owner"),
    "dependent_uses_replacement": ("SOC 2 CC8.1", "ISO 27001 A.8.32", "The change landed as intended"),
    "dependent_healthy": ("SOC 2 CC7.2", "ISO 27001 A.8.16", "The system is monitored and healthy after the change"),
    "regression_passes": ("SOC 2 CC8.1", "ISO 27001 A.8.29", "Testing confirms the change did not break function"),
    "service_healthy": ("SOC 2 CC7.2", "ISO 27001 A.8.16", "The system is monitored and healthy after the change"),
    "error_rate_below": ("SOC 2 CC7.2", "ISO 27001 A.8.16", "Error rates are within normal bounds"),
    "caller_healthy": ("SOC 2 CC7.2", "ISO 27001 A.8.16", "Dependent systems recovered"),
    "synthetic_checkout_passes": ("SOC 2 CC7.2", "ISO 27001 A.8.16", "The business transaction works end to end"),
    "running_known_good": ("SOC 2 CC8.1", "ISO 27001 A.8.32", "The system runs an approved, known-good version"),
    "bad_revision_blocked": ("SOC 2 CC8.1", "ISO 27001 A.8.32", "The faulty change cannot be redeployed"),
    "pipeline_resumed": ("SOC 2 CC8.1", "ISO 27001 A.8.32", "Change control is operating again, not left frozen"),
    "pipeline_paused": ("SOC 2 CC8.1", "ISO 27001 A.8.32", "Automated deployment is held during the change"),
    "referral_received": ("Care follow-up", "Patient safety", "The referral reached the clinic it was meant for"),
    "prescription_at_pharmacy": ("Care follow-up", "Patient safety",
                                 "The pharmacy has the prescription the record says was sent"),
    "appointment_booked": ("Care follow-up", "Patient safety", "The patient has an appointment, not a promise"),
    "patient_reached": ("Care follow-up", "Patient safety", "The patient knows what happens next"),
    "clinician_notified": ("Urgent results", "Patient safety", "An urgent result reaches a doctor"),
    "clinician_acknowledged": ("Urgent results", "Patient safety",
                               "A doctor has taken responsibility for the result"),
    "loop_closed_in_record": ("Care follow-up", "Patient safety", "The record matches what really happened"),
    "appointment_moved": ("Care continuity", "Patient safety", "The appointment is with a doctor who is in"),
    "no_double_booking": ("Care continuity", "Patient safety", "No two people were put in the same slot"),
    "session_cleared": ("Care continuity", "Patient safety",
                        "Nobody is left booked with a doctor who is not coming in"),
}


def control_for(method):
    return CONTROLS.get(method, ("--", "--", "Operational verification"))


def leak_conditions(rel):
    """Closure for a scanner finding: the key is attributed, it is dead, and the file is clean.

    Reuses the credential checks when the key is still live and has to be rotated; when it was already
    revoked there is nothing to rotate, and closure is just "prove it is dead and clean up the file".
    """
    conds = build_conditions(rel)
    methods = {c.method for c in conds}
    ids = {c.id for c in conds}
    for r in (x for x in rel if x["rel"] == "leak"):
        head = [Condition(
            id="leak-attributed",
            description=f"The leaked key {r['fp']} belongs to a credential with a known owner",
            expected="the vault holds a credential with this fingerprint, and it has an owner",
            method="leak_attributed", args={"fp": r["fp"]})]
        if "old_credential_rejected" not in methods:
            head.append(Condition(
                id="leak-key-dead", description=f"The leaked key {r['fp']} is rejected when used",
                expected="authentication with the leaked key fails",
                method="old_credential_rejected", args={"fp": r["fp"]}))
        if f"repo:{r['path']}-scrubbed" not in ids:
            head.append(Condition(
                id=f"repo:{r['path']}-scrubbed",
                description=f"The leaked key is removed from {r['path']}",
                expected="file no longer contains the leaked key",
                method="secret_removed_from_repo", args={"path": r["path"], "fp": r["fp"]}))
        conds = head + conds
    return conds


def care_conditions(rel):
    """What has to be true before the clinic's record may say any of this is finished.

    Things the record already calls done are checked as well. Proving one really did happen is
    worth as much as putting right the ones that did not.
    """
    conds = []
    for h in (r for r in rel if r["rel"] == "follow_up"):
        oid, pid, who, place = h["order"], h["patient"], h["patient_name"], h["place"]
        if h["kind"] == "referral":
            conds += [
                Condition(id=f"{oid}-received", description=f"The {place} has {who}'s referral",
                          expected="the referral is in the receiving clinic's own system",
                          method="referral_received", args={"order": oid, "specialty": h["specialty"]}),
                Condition(id=f"{oid}-appointment", description=f"{who} has a real appointment at the {place}",
                          expected="an appointment exists in their booking system",
                          method="appointment_booked", args={"patient": pid, "specialty": h["specialty"]}),
                Condition(id=f"{oid}-patient-told", description=f"{who} has replied, so she knows about it",
                          expected="a message was delivered and answered", method="patient_reached",
                          args={"patient": pid})]
        elif h["kind"] == "result":
            conds.append(Condition(
                id=f"{oid}-doctor-told", description=f"{h['doctor']} has been sent {who}'s result",
                expected="the result is in front of the doctor who ordered it",
                method="clinician_notified", args={"order": oid}))
            if h["urgent"]:
                conds.append(Condition(
                    id=f"{oid}-acknowledged",
                    description=f"A doctor has seen and signed off {who}'s urgent result",
                    expected="a doctor has acknowledged it", method="clinician_acknowledged",
                    args={"order": oid}))
        elif h["kind"] == "prescription":
            conds += [
                Condition(id=f"{oid}-at-pharmacy", description=f"The pharmacy has {who}'s {h['drug']}",
                          expected="the prescription is in the pharmacy's queue",
                          method="prescription_at_pharmacy", args={"order": oid}),
                Condition(id=f"{oid}-patient-told", description=f"{who} has replied, so he knows to collect it",
                          expected="a message was delivered and answered", method="patient_reached",
                          args={"patient": pid})]
        conds.append(Condition(
            id=f"{oid}-record-true",
            description=f"The record only calls {who}'s {KIND_LABEL_V[h['kind']]} done if it really is",
            expected="the record agrees with what the other systems show",
            method="loop_closed_in_record", args={"order": oid}))
    return conds


def cover_conditions(rel):
    """What has to be true before a sick doctor's list can be called sorted."""
    conds = []
    off = next(r for r in rel if r["rel"] == "absence")
    for m in (r for r in rel if r["rel"] == "booking"):
        if not m["movable"]:
            continue
        conds.append(Condition(
            id=f"{m['appointment']}-moved",
            description=f"{m['patient_name']} is booked with a doctor who is actually in",
            expected="the appointment is with someone other than the absent doctor",
            method="appointment_moved", args={"appointment": m["appointment"], "from_doctor": off["doctor"]}))
        conds.append(Condition(
            id=f"{m['appointment']}-told",
            description=f"{m['patient_name']} has replied, so she knows the time changed",
            expected="a message was delivered and answered", method="patient_reached",
            args={"patient": m["patient"]}))
    conds.append(Condition(
        id="no-double-booking", description="Nobody was put into a slot that was already taken",
        expected="no two booked appointments share a doctor and a time",
        method="no_double_booking", args={}))
    conds.append(Condition(
        id="session-cleared",
        description=f"Nobody is still booked in with {off['doctor_name']}, who is not coming in",
        expected="the absent doctor's list is empty", method="session_cleared",
        args={"doctor": off["doctor"]}))
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
    if a.type == "pause_pipeline":
        return [("pipeline_paused", {"service": a.target})]
    if a.type == "rollback_service":
        return [("running_known_good", {"service": a.target, "bad_revision": p["from_revision"],
                                        "good_revisions": [p["to_revision"]]}),
                ("service_healthy", {"service": a.target})]
    if a.type == "resume_pipeline":
        return [("pipeline_resumed", {"service": a.target}),
                ("bad_revision_blocked", {"service": a.target, "revision": p["block_revision"]}),
                ("running_known_good", {"service": a.target, "bad_revision": p["block_revision"],
                                        "good_revisions": [p["expect_revision"]]})]
    if a.type == "resend_referral":
        return [("referral_received", {"order": a.target, "specialty": p["specialty"]})]
    if a.type == "book_appointment":
        return [("appointment_booked", {"patient": p["patient"], "specialty": p["specialty"]})]
    if a.type == "contact_patient":
        return [("patient_reached", {"patient": p["patient"]})]
    if a.type == "notify_clinician":
        return [("clinician_notified", {"order": a.target})]
    if a.type == "close_loop":
        return [("loop_closed_in_record", {"order": a.target})]
    if a.type == "resend_prescription":
        return [("prescription_at_pharmacy", {"order": a.target})]
    if a.type == "move_appointment":
        return [("appointment_moved", {"appointment": a.target, "from_doctor": p["from_doctor"]}),
                ("no_double_booking", {})]
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
        if a.type == "pause_pipeline":
            return not sb.cloud.pipeline(a.target)["auto_deploy"]
        if a.type == "rollback_service":
            return sb.cloud.deployment(a.target)["current"] == p["to_revision"]
        if a.type == "resume_pipeline":
            return sb.cloud.pipeline(a.target)["auto_deploy"]
        if a.type == "resend_referral":
            return sb.booking.received(a.target, sb.records.order(a.target)["specialty"])
        if a.type == "book_appointment":
            return sb.booking.appointment_for(p["patient"], p["specialty"]) is not None
        if a.type == "contact_patient":
            return any(m["kind"] == p["channel"] for m in sb.outreach.messages(p["patient"]))
        if a.type == "notify_clinician":
            return bool(sb.records.notified(a.target))
        if a.type == "close_loop":
            return sb.records.loop_closed(a.target)
        if a.type == "resend_prescription":
            return sb.pharmacy.has(a.target)
        if a.type == "move_appointment":
            ap = sb.schedule.appointment(a.target)
            return bool(ap) and ap["doctor"] == p["to_doctor"] and ap["at"] == p["to_time"]
    except Exception:
        return None
    return None
