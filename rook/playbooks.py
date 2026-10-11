"""Playbooks: the incident types Rook can resolve.

The engine (plan -> authorize -> execute -> reconcile -> verify -> close on evidence) is the same for
every incident. A playbook supplies what differs: how an incident is triggered, what Rook reads to
investigate it, the remediation it plans, and the closure checks that must hold before it is closed.

- offboarding: someone left, but their access and keys live on (access management)
- outage: a production service is failing after a change (cloud / IT incident)
- leak: a secrets scanner found a credential hardcoded in a repository (non-human identity)
- care: things in a clinic the record calls done and nobody ever actually completed
- cover: a doctor calls in sick and a day of appointments has to be moved, told and checked
"""
import datetime
from .domain import Action
from .sandbox import DAY, MATCH_DAY, SPECIALTY, playbook_of
from .verification import (build_conditions, care_conditions, cover_conditions, fixtures_conditions,
                           leak_conditions, outage_conditions)


# ================================================================ playbook: access & offboarding

def investigate(sb, subject):
    """Observed relationships, graph and findings. Fingerprints and paths only; no secret values."""
    rel = []
    person = sb.apps.directory(subject)
    for name in ("github", "cloud", "pm"):
        for u, acc in sb.account_service(name).accounts().items():
            if acc["owner"] == subject:
                rel.append({"rel": "has_account", "service": name, "user": u, "status": acc["status"]})
    for cid in sorted(sb.vault.creds()):
        m = sb.vault.meta(cid)
        if m["owner"] != subject:
            continue
        active = [v for v in m["versions"] if v["status"] == "active"]
        cur = active[-1] if active else m["versions"][-1]
        deps = sb.dependents_of_fp(cur["fp"])
        exposed = sb.github.find_secret(cur["fp"])
        rel.append({"rel": "owns_credential", "cred": cid, "status": "active" if active else "inactive",
                    "version": cur["v"], "fp": cur["fp"], "purpose": m["purpose"],
                    "created_by": m["created_by"], "created_at": m["created_at"],
                    "dependents": deps, "recorded_used_by": m["used_by"],
                    "unrecorded_dependents": [d for d in deps if d not in m["used_by"]],
                    "exposed_in": exposed,
                    "exposure_history": [h for p in exposed for h in sb.github.commit_history(p)]})
    for o in sb.ownerless_accounts():          # not this subject's, but found on the same sweep
        rel.append({"rel": "ownerless_account", **o})
    return person, rel, build_graph(subject, person, rel), findings(subject, person, rel)


def build_graph(subject, person, rel):
    nodes = [{"id": subject, "kind": "identity", "label": person.get("name", subject),
              "status": person.get("status", "unknown"), "detail": person.get("type", "")}]
    edges = []
    for r in rel:
        if r["rel"] == "has_account":
            nid = f"{r['service']}:{r['user']}"
            nodes.append({"id": nid, "kind": "account", "label": f"{r['service']} / {r['user']}", "status": r["status"]})
            edges.append({"from": subject, "to": nid, "rel": "has account"})
        elif r["rel"] == "owns_credential":
            nodes.append({"id": r["cred"], "kind": "credential", "label": f"{r['cred']} ({r['fp']})",
                          "status": r["status"], "detail": r["purpose"]})
            edges.append({"from": subject, "to": r["cred"], "rel": "created"})
            for d in r["dependents"]:
                nodes.append({"id": d, "kind": "dependent", "label": d, "status": "uses old key",
                              "detail": "not in vault metadata" if d in r["unrecorded_dependents"] else ""})
                edges.append({"from": d, "to": r["cred"], "rel": "authenticates with"})
            for p in r["exposed_in"]:
                nodes.append({"id": f"repo:{p}", "kind": "repo", "label": p, "status": "exposed"})
                edges.append({"from": r["cred"], "to": f"repo:{p}", "rel": "committed to"})
    return {"nodes": nodes, "edges": edges}


def findings(subject, person, rel):
    out = []
    name = person.get("name", subject)
    dis = [f"{r['service']}/{r['user']}" for r in rel if r["rel"] == "has_account" and r["status"] == "disabled"]
    act = [f"{r['service']}/{r['user']}" for r in rel if r["rel"] == "has_account" and r["status"] == "active"]
    out.append({"severity": "info", "text": f"{name} ({person.get('type', 'unknown type')}) is "
                f"{person.get('status', 'unknown')} in the directory since {person.get('disabled_at', 'n/a')}.",
                "evidence": {"directory_status": person.get("status")}})
    if act:
        out.append({"severity": "medium", "text": f"Accounts still active after offboarding: {', '.join(act)}. "
                    f"Already disabled: {', '.join(dis) or 'none'}.", "evidence": {"active": act, "disabled": dis}})
    for r in rel:
        if r["rel"] != "owns_credential" or r["status"] != "active":
            continue
        out.append({"severity": "high", "text": f"{r['purpose']} {r['cred']} ({r['fp']}) created by {r['created_by']} "
                    f"on {r['created_at'][:10]} is still active.", "evidence": {"cred": r["cred"], "version": r["version"]}})
        if r["dependents"]:
            out.append({"severity": "high", "text": f"It is in live use by {', '.join(r['dependents'])}; revoking it "
                        "first would take them down, so each must move to a replacement key before revocation.",
                        "evidence": {"dependents": r["dependents"]}})
        if r["unrecorded_dependents"]:
            out.append({"severity": "medium", "text": f"{', '.join(r['unrecorded_dependents'])} uses the key but is "
                        "missing from the vault's metadata; found by scanning live configuration.",
                        "evidence": {"recorded_used_by": r["recorded_used_by"]}})
        for h in r["exposure_history"]:
            out.append({"severity": "high", "text": f"The key is committed in {h['repo']}/{h['path']} "
                        f"(by {h['actor']} on {h['at'][:10]}), so it must be treated as leaked.", "evidence": h})
    for r in rel:
        if r["rel"] == "ownerless_account":
            out.append({"severity": "medium", "text": f"{r['service']} account '{r['user']}' has no owner in any "
                        "directory. Rook will not touch access it cannot attribute; a person needs to assign or "
                        "remove it.", "evidence": {"service": r["service"], "user": r["user"], "status": r["status"]}})
    return out


def explain(person, rel):
    return " ".join(f["text"] for f in findings(person.get("id", ""), person, rel)[1:]) if rel else ""


# ---------------------------------------------------------------- planning

def sentence(t):
    """Start a reason with a capital without flattening the names inside it."""
    return t[:1].upper() + t[1:] if t else t


def make_action(iid, n, type, target, params, depends_on=(), summary="", risk="low"):
    return Action(id=f"{iid}-a{n}", incident_id=iid, type=type, target=target, params=params,
                  depends_on=list(depends_on), summary=summary, risk=risk,
                  idem_key=f"{iid}:{type}:{params.get('service','')}:{target}")


class RuleBasedPlanner:
    """Deterministic plan: contain accounts, then replace -> repoint dependents -> revoke."""
    def plan(self, rel, iid):
        acts = []

        def add(t, target, deps=(), summary="", risk="low", **p):
            a = make_action(iid, len(acts) + 1, t, target, p, deps, summary, risk)
            acts.append(a)
            return a
        for r in rel:
            if r["rel"] == "has_account" and r["status"] == "active":
                add("disable_account", r["user"], service=r["service"],
                    summary=f"Disable the leftover {r['service']} account '{r['user']}'.")
        for r in rel:
            if r["rel"] != "owns_credential" or r["status"] != "active":
                continue
            c = r["cred"]
            issue = add("issue_replacement", c, service="vault", old_version=r["version"], old_fp=r["fp"],
                        summary=f"Create a new version of {c}. The old key keeps working for now.")
            ups = [add("update_dependent", d, [issue.id], service=d.split(":")[0], cred_id=c,
                       old_fp=r["fp"], old_version=r["version"],
                       summary=f"Point {d} at the new key and check it is healthy.") for d in r["dependents"]]
            rev = add("revoke_credential", c, [u.id for u in ups] + [issue.id], service="vault", cred_id=c,
                      version=r["version"], old_fp=r["fp"], risk="high",
                      summary=f"Permanently revoke the old key {r['fp']}. Anything still using it will stop working.")
            for path in r.get("exposed_in", []):
                add("scrub_exposed_secret", path, [rev.id], service="github", cred_id=c, old_fp=r["fp"],
                    summary=f"Remove the leaked (now dead) key from {path} so scanners stop flagging it.")
        return acts




class Offboarding:
    key = "offboarding"
    name = "Access & offboarding"
    trigger = "A completed offboarding ticket"
    contain_type, contain_label = "revoke_credential", "Old key dead after"

    def find_subject(self, sb):
        done = sb.pm.completed_offboardings()
        return next(iter(done.values()))["subject"] if done else None

    def investigate(self, sb, subject):
        return investigate(sb, subject)

    def title(self, info, subject):
        return f"Active credential after offboarding: {info.get('name', subject)}"

    def discovery(self, rel):
        creds = [r for r in rel if r["rel"] == "owns_credential"]
        deps = [d for r in creds for d in r["dependents"]]
        return ("config scan for " + ", ".join(r["fp"] for r in creds), deps,
                {"dependents": len(deps), "unrecorded": sum(len(r.get("unrecorded_dependents", [])) for r in creds)})

    def plan(self, rel, iid):
        return RuleBasedPlanner().plan(rel, iid)

    def conditions(self, rel):
        return build_conditions(rel)

    def closed_summary(self, n):
        return (f"Closed with evidence: all {n} actions were independently verified and every closure "
                "check passed. The old key is rejected, the replacement works, and every dependent is healthy.")

    def follow_ups(self, inc, acts):
        out = []
        for r in inc.relationships:
            if r["rel"] == "ownerless_account":
                out.append(f"Assign an owner to, or remove, the ownerless {r['service']} account '{r['user']}'.")
        if any(a.type == "scrub_exposed_secret" and a.status.value == "verified" for a in acts):
            paths = [a.target for a in acts if a.type == "scrub_exposed_secret"]
            out.append(f"Git history of {', '.join(paths)} still contains the revoked key. It no longer works; "
                       "rewrite history only if policy requires it.")
        for a in acts:
            if a.result.get("rolled_back"):
                out.append(f"{a.target} was rolled back to the previous key after its update failed. Fix the service, "
                           "then run the incident again.")
        return out

    def declines(self, inc, acts):
        """Things Rook deliberately did not do, and why. Never acts on access it cannot attribute."""
        return [{"what": f"Touch the {r['service']} account '{r['user']}'",
                 "why": "No directory owns this account, so Rook cannot tell whose access it is.",
                 "rule": "R2-ownership"}
                for r in inc.relationships if r["rel"] == "ownerless_account"]

    def impact(self, sb, inc):
        """Services that relied on the leaked key when the incident began, and are down right now."""
        deps = [d for r in inc.relationships if r["rel"] == "owns_credential" for d in r["dependents"]]
        return [d for d in deps if not sb.health(d)]


# ================================================================ playbook: service outage

def investigate_outage(sb, subject):
    """Read the alert, live health, deploy history, pipeline, database and callers of a failing service."""
    svc = subject.split(":", 1)[1]
    d, p = sb.cloud.deployment(svc), sb.cloud.pipeline(svc)
    cur = d["current"]
    rev = sb.cloud.revision(svc, cur)
    info = {"name": svc, "team": d["team"]}
    rel = []
    alert = next(((tid, t) for tid, t in sb.pm.open_alerts().items() if t["subject"] == subject), None)
    if alert:
        rel.append({"rel": "alert", "ticket": alert[0], "title": alert[1]["title"], "opened_at": alert[1]["opened_at"]})
    healthy = sb.cloud.service_healthy(svc)
    rel.append({"rel": "service_state", "service": svc, "healthy": healthy, "error_rate": sb.cloud.error_rate(svc),
                "revision": cur, "team": d["team"]})
    prev_n = max((int(k) for k in d["revisions"] if int(k) < cur), default=None)
    if prev_n is not None:
        prev = sb.cloud.revision(svc, prev_n)
        changed = {k: [prev["env"].get(k), v] for k, v in rev["env"].items() if prev["env"].get(k) != v}
        mins = None
        if alert:
            from datetime import datetime
            t = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
            mins = round((t(alert[1]["opened_at"]) - t(rev["deployed_at"])).total_seconds() / 60)
        rel.append({"rel": "deploy", "service": svc, "revision": cur, "previous": prev_n, "at": rev["deployed_at"],
                    "by": rev["deployed_by"], "commit": rev["commit"], "message": rev["message"], "changed": changed,
                    "minutes_before_alert": mins})
    for k, r in sorted(d["revisions"].items(), key=lambda x: -int(x[0])):
        if int(k) != cur and r["healthy_minutes"] >= 60:
            rel.append({"rel": "known_good", "service": svc, "revision": int(k), "healthy_minutes": r["healthy_minutes"],
                        "commit": r["commit"]})
            break
    rel.append({"rel": "pipeline", "service": svc, "auto_deploy": p["auto_deploy"], "desired": p["desired"],
                "blocked": list(p["blocked"])})
    for host in sorted({rev["env"].get("DB_HOST")} | {sb.cloud.revision(svc, k)["env"].get("DB_HOST")
                                                     for k in d["revisions"]}):
        rel.append({"rel": "database", "service": svc, "host": host, "state": sb.cloud.database(host),
                    "used_by_running": host == rev["env"].get("DB_HOST")})
    for c in sb.callers_of(svc):
        rel.append({"rel": "downstream", "service": svc, "caller": c, "healthy": sb.caller_healthy(c, svc)})
    return info, rel, outage_graph(subject, rel), outage_findings(rel)


def outage_graph(subject, rel):
    st = next(r for r in rel if r["rel"] == "service_state")
    nodes = [{"id": subject, "kind": "service", "label": st["service"],
              "status": "healthy" if st["healthy"] else f"failing · {int(st['error_rate'] * 100)}% errors"}]
    edges = []
    for r in rel:
        if r["rel"] == "alert":
            nodes.append({"id": r["ticket"], "kind": "alert", "label": r["ticket"], "status": "firing"})
            edges.append({"from": r["ticket"], "to": subject, "rel": "fired on"})
        elif r["rel"] == "downstream":
            nodes.append({"id": r["caller"], "kind": "caller", "label": r["caller"],
                          "status": "healthy" if r["healthy"] else "failing"})
            edges.append({"from": r["caller"], "to": subject, "rel": "calls"})
        elif r["rel"] == "deploy":
            nodes.append({"id": f"rev:{r['revision']}", "kind": "revision", "label": f"rev {r['revision']} · {r['commit']}",
                          "status": "running · suspect"})
            edges.append({"from": subject, "to": f"rev:{r['revision']}", "rel": "running"})
        elif r["rel"] == "known_good":
            nodes.append({"id": f"rev:{r['revision']}", "kind": "revision", "label": f"rev {r['revision']} · {r['commit']}",
                          "status": "known good"})
            edges.append({"from": subject, "to": f"rev:{r['revision']}", "rel": "last good"})
        elif r["rel"] == "database" and r["used_by_running"]:
            nodes.append({"id": f"db:{r['host']}", "kind": "host", "label": r["host"], "status": r["state"]})
            edges.append({"from": subject, "to": f"db:{r['host']}", "rel": "connects to"})
        elif r["rel"] == "pipeline":
            nodes.append({"id": f"pipeline:{r['service']}", "kind": "pipeline", "label": f"{r['service']} pipeline",
                          "status": f"auto-deploy {'on' if r['auto_deploy'] else 'off'} · wants rev {r['desired']}"})
    return {"nodes": nodes, "edges": edges}


def outage_findings(rel):
    g = {r["rel"]: r for r in rel}
    st, svc = g["service_state"], g["service_state"]["service"]
    out = []
    if "alert" in g:
        out.append({"severity": "info", "text": f"{g['alert']['ticket']} fired at {g['alert']['opened_at'][11:16]} UTC: "
                    f"{g['alert']['title']}.", "evidence": {"ticket": g["alert"]["ticket"]}})
    if not st["healthy"]:
        out.append({"severity": "high", "text": f"{svc} is failing its health check and {int(st['error_rate'] * 100)}% of "
                    f"requests return errors. Owner: {st['team']} team.", "evidence": {"error_rate": st["error_rate"]}})
    for r in rel:
        if r["rel"] == "downstream" and not r["healthy"]:
            out.append({"severity": "high", "text": f"{r['caller']} calls {svc} and is failing too, so customers "
                        "cannot complete checkout.", "evidence": {"caller": r["caller"]}})
    dep = g.get("deploy")
    if dep:
        ch = ", ".join(f"{k} from {a} to {b}" for k, (a, b) in dep["changed"].items()) or "no config"
        when = f"{dep['minutes_before_alert']} minute(s) before the alert" if dep["minutes_before_alert"] is not None else ""
        out.append({"severity": "high", "text": f"Revision {dep['revision']} was deployed {when} by {dep['by']} "
                    f"(commit {dep['commit']}, \"{dep['message']}\"). It changed {ch}.", "evidence": dep})
    for r in rel:
        if r["rel"] == "database" and r["used_by_running"] and r["state"] != "up":
            out.append({"severity": "high", "text": f"The running revision connects to {r['host']}, which is "
                        f"{r['state']}. That is the most likely cause.", "evidence": r})
        elif r["rel"] == "database" and not r["used_by_running"] and r["state"] == "up":
            out.append({"severity": "info", "text": f"{r['host']} is up, so rolling back to a revision that uses it "
                        "should restore service.", "evidence": r})
    if "known_good" in g:
        k = g["known_good"]
        out.append({"severity": "medium", "text": f"Revision {k['revision']} ran healthy for {k['healthy_minutes'] // 60} "
                    "hours before that, so it is a known-good rollback target.", "evidence": k})
    p = g.get("pipeline")
    if p and p["auto_deploy"] and dep and p["desired"] == dep["revision"]:
        out.append({"severity": "medium", "text": f"The deploy pipeline has auto-deploy on and still wants revision "
                    f"{dep['revision']}. A rollback would be overwritten straight away unless the pipeline is paused "
                    "first, and a paused pipeline must not be forgotten afterwards.", "evidence": p})
    return out


class Outage:
    key = "outage"
    name = "Service outage"
    trigger = "A monitoring alert"
    contain_type, contain_label = "rollback_service", "Service restored after"

    def find_subject(self, sb):
        alerts = sb.pm.open_alerts()
        return next(iter(alerts.values()))["subject"] if alerts else None

    def investigate(self, sb, subject):
        return investigate_outage(sb, subject)

    def title(self, info, subject):
        return f"{info['name']} outage: failing after a deploy"

    def discovery(self, rel):
        callers = [r["caller"] for r in rel if r["rel"] == "downstream"]
        st = next(r for r in rel if r["rel"] == "service_state")
        return (f"callers and deploy history of {st['service']}", callers,
                {"dependents": len(callers), "deploys_checked": sum(r["rel"] in ("deploy", "known_good") for r in rel)})

    def plan(self, rel, iid):
        acts = []

        def add(t, target, deps=(), summary="", risk="low", **p):
            a = make_action(iid, len(acts) + 1, t, target, p, deps, summary, risk)
            acts.append(a)
            return a
        g = {r["rel"]: r for r in rel}
        st, dep, good, pipe = g["service_state"], g.get("deploy"), g.get("known_good"), g.get("pipeline")
        if st["healthy"] or not dep or not good:
            return acts                                   # nothing safe to do automatically; escalate
        svc = st["service"]
        pause = None
        if pipe and pipe["auto_deploy"]:
            pause = add("pause_pipeline", svc, service="cloud",
                        summary=f"Pause auto-deploy for {svc} so it cannot redeploy revision {dep['revision']} over the fix.")
        rb = add("rollback_service", svc, [pause.id] if pause else [], service="cloud",
                 to_revision=good["revision"], from_revision=dep["revision"], risk="medium",
                 summary=f"Roll {svc} back from revision {dep['revision']} to known-good revision {good['revision']}.")
        if pipe:
            add("resume_pipeline", svc, [rb.id], service="cloud", block_revision=dep["revision"],
                expect_revision=good["revision"],
                summary=f"Turn auto-deploy back on with revision {dep['revision']} blocked, so the pipeline is not "
                        "left frozen and the bad change cannot come back.")
        return acts

    def conditions(self, rel):
        return outage_conditions(rel)

    def closed_summary(self, n):
        return (f"Closed with evidence: all {n} actions were independently verified. The service is back on a "
                "known-good revision, errors are normal, callers are healthy, a test order goes through, and the "
                "pipeline is running again with the bad revision blocked.")

    def follow_ups(self, inc, acts):
        out = []
        g = {r["rel"]: r for r in inc.relationships}
        dep = g.get("deploy")
        by = {a.type: a for a in acts}
        rb, res = by.get("rollback_service"), by.get("resume_pipeline")
        if dep and res and res.status.value == "verified":
            out.append(f"Revision {dep['revision']} (commit {dep['commit']}) is blocked from redeploying. Fix it "
                       f"({', '.join(dep['changed']) or 'the change'}) before shipping it again.")
        if rb and rb.status.value == "failed" and rb.evidence.get("running_revision") == rb.params.get("to_revision"):
            out.append(f"Rolling back to revision {rb.params['to_revision']} did not restore {rb.target}, so the deploy is "
                       "not the whole cause. Check the database, network and recent infrastructure changes.")
        if any(a.type == "pause_pipeline" and a.status.value == "verified" for a in acts) and \
                not (res and res.status.value == "verified"):
            out.append(f"The {g['service_state']['service']} pipeline is still paused on purpose. Resume it once the "
                       "service is fixed, or it will stay frozen.")
        if not acts:
            out.append("Rook found no known-good revision to roll back to, so a person needs to take this incident.")
        return out

    def declines(self, inc, acts):
        out = []
        g = {r["rel"]: r for r in inc.relationships}
        if not acts and g.get("service_state") and not g["service_state"]["healthy"]:
            out.append({"what": "Roll the service back automatically",
                        "why": "There is no revision with a healthy track record to roll back to.",
                        "rule": "R8-known-good"})
        if any(a.type == "pause_pipeline" and a.status.value == "verified" for a in acts) and \
                not any(a.type == "resume_pipeline" and a.status.value == "verified" for a in acts):
            out.append({"what": "Leave the deploy pipeline running",
                        "why": "The pipeline is paused on purpose until the service is healthy again.",
                        "rule": "R4-safe-order"})
        return out

    def impact(self, sb, inc):
        st = next(r for r in inc.relationships if r["rel"] == "service_state")
        svc = st["service"]
        return ([f"cloud:{svc}"] if not sb.cloud.service_healthy(svc) else []) + \
            [c for c in sb.callers_of(svc) if not sb.caller_healthy(c, svc)]




# ================================================================ playbook: leaked secret

def _days_since(iso):
    try:
        then = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return max(0, (datetime.datetime.now(datetime.timezone.utc) - then).days)


def leak_alert(sb):
    return next(iter(sb.pm.open_leak_alerts().items()), (None, None))


def leak_subject(sb):
    """Attribute the finding before the incident opens: the subject is whoever owns the key.

    Policy scopes every action to the incident's subject, so an unattributable finding gets the
    path as its subject instead, which no credential action can ever match.
    """
    tid, alert = leak_alert(sb)
    if alert is None:
        return None
    fps = sb.github.secrets_in(alert["path"])
    cid = sb.vault.find_by_fp(fps[0]) if fps else None
    return (sb.vault.owner(cid) if cid else None) or f"leak:{alert['path']}"


def investigate_leak(sb, subject):
    """Read the scanner finding, probe whether the key still works, and find everything using it."""
    tid, alert = leak_alert(sb)
    path = alert["path"]
    fps = sb.github.secrets_in(path)
    f = fps[0] if fps else None
    history = sb.github.commit_history(path)
    first = history[0] if history else {}
    cid = sb.vault.find_by_fp(f) if f else None
    rel = [{"rel": "leak", "alert": tid, "scanner": alert.get("scanner", "scanner"), "path": path,
            "repo": path.split("/", 1)[0], "fp": f, "credential": cid,
            "still_valid": sb.vault.authenticate_fp(f) if f else False,
            "exposed_by": first.get("actor"), "exposed_at": first.get("at"),
            "days_exposed": _days_since(first.get("at")),
            "live_users": sb.dependents_of_fp(f) if f else []}]
    info = {"name": path, "alert": tid}
    if cid:
        m = sb.vault.meta(cid)
        active = [v for v in m["versions"] if v["status"] == "active"]
        cur = active[-1] if active else m["versions"][-1]
        deps = sb.dependents_of_fp(cur["fp"])
        rel.append({"rel": "owns_credential", "cred": cid,
                    "status": "active" if active else "inactive", "version": cur["v"], "fp": cur["fp"],
                    "purpose": m["purpose"], "created_by": m["created_by"], "created_at": m["created_at"],
                    "dependents": deps, "recorded_used_by": m["used_by"],
                    "unrecorded_dependents": [d for d in deps if d not in m["used_by"]],
                    "exposed_in": sb.github.find_secret(cur["fp"]),
                    "exposure_history": [h for pth in sb.github.find_secret(cur["fp"])
                                         for h in sb.github.commit_history(pth)]})
        info["name"] = m["purpose"]
    return info, rel, leak_graph(rel), leak_findings(rel)


def leak_graph(rel):
    g = {r["rel"]: r for r in rel}
    lk = g["leak"]
    # "not valid" only means "already dead" once the key is attributed; an unknown key's state is unknown.
    attributed = any(r["rel"] == "owns_credential" for r in rel)
    status = ("live key leaked" if lk["still_valid"] else
              "key already dead" if attributed else "unidentified key")
    nodes = [{"id": f"repo:{lk['path']}", "kind": "repo", "label": lk["path"], "status": status,
              "detail": f"exposed {lk['days_exposed']} days" if lk["days_exposed"] is not None else ""}]
    edges = []
    cred = g.get("owns_credential")
    if cred:
        nodes.append({"id": cred["cred"], "kind": "credential",
                      "label": f"{cred['cred']} ({cred['fp']})", "status": cred["status"],
                      "detail": cred["purpose"]})
        edges.append({"from": cred["cred"], "to": f"repo:{lk['path']}", "rel": "committed to"})
        for d in cred["dependents"]:
            nodes.append({"id": d, "kind": "dependent", "label": d, "status": "uses leaked key",
                          "detail": "not in vault metadata" if d in cred["unrecorded_dependents"] else ""})
            edges.append({"from": d, "to": cred["cred"], "rel": "authenticates with"})
    else:
        nodes.append({"id": "unattributed", "kind": "credential", "label": lk["fp"] or "unreadable",
                      "status": "no owner", "detail": "matches no credential in the vault"})
        edges.append({"from": "unattributed", "to": f"repo:{lk['path']}", "rel": "found in"})
    return {"nodes": nodes, "edges": edges}


def leak_findings(rel):
    g = {r["rel"]: r for r in rel}
    lk, cred = g["leak"], g.get("owns_credential")
    out = [{"severity": "info",
            "text": f"{lk['scanner']} flagged a hardcoded credential in {lk['path']}"
                    + (f", committed by {lk['exposed_by']} on {lk['exposed_at'][:10]}" if lk.get("exposed_at") else "")
                    + (f" and exposed for {lk['days_exposed']} days." if lk["days_exposed"] is not None else "."),
            "evidence": {"alert": lk["alert"], "path": lk["path"], "fp": lk["fp"]}}]
    if cred is None:
        out.append({"severity": "high",
                    "text": "The key matches no credential in the vault, so Rook cannot tell who owns it or what "
                            "would break if it were revoked. It will not touch an unattributable credential; a "
                            "person has to identify it.",
                    "evidence": {"fp": lk["fp"]}})
        return out
    if lk["still_valid"]:
        out.append({"severity": "high",
                    "text": f"The leaked key is still live: a request signed with {lk['fp']} is accepted right now. "
                            "Finding it is not the same as closing it.",
                    "evidence": {"fp": lk["fp"], "credential": cred["cred"]}})
    else:
        out.append({"severity": "info",
                    "text": f"The leaked key {lk['fp']} is already revoked, so rotating it again would be churn. "
                            "The file still has to be cleaned up and the key proven dead.",
                    "evidence": {"fp": lk["fp"], "credential": cred["cred"]}})
    if cred["dependents"]:
        out.append({"severity": "high" if lk["still_valid"] else "medium",
                    "text": f"{cred['purpose']} {cred['cred']} is in live use by {', '.join(cred['dependents'])}, "
                            "so revoking it before each one moves to a replacement would take them down.",
                    "evidence": {"dependents": cred["dependents"]}})
    if cred["unrecorded_dependents"]:
        out.append({"severity": "medium",
                    "text": f"{', '.join(cred['unrecorded_dependents'])} uses the key but is missing from the "
                            "vault's metadata; found by scanning live configuration.",
                    "evidence": {"recorded_used_by": cred["recorded_used_by"]}})
    for pth in cred["exposed_in"]:
        if pth != lk["path"]:
            out.append({"severity": "medium",
                        "text": f"The same key is also committed in {pth}, which the scanner did not report.",
                        "evidence": {"path": pth}})
    return out


class LeakedSecret:
    key = "leak"
    name = "Leaked credential"
    trigger = "A secrets-scanner finding"
    contain_type, contain_label = "revoke_credential", "Leaked key dead after"

    def find_subject(self, sb):
        return leak_subject(sb)

    def investigate(self, sb, subject):
        return investigate_leak(sb, subject)

    def title(self, info, subject):
        return f"Leaked credential in a repository: {info.get('name', subject)}"

    def discovery(self, rel):
        g = {r["rel"]: r for r in rel}
        lk, cred = g["leak"], g.get("owns_credential")
        deps = cred["dependents"] if cred else []
        return (f"config scan for {lk['fp']}", deps,
                {"dependents": len(deps), "still_valid": lk["still_valid"],
                 "attributed": cred is not None,
                 "unrecorded": len(cred["unrecorded_dependents"]) if cred else 0})

    def plan(self, rel, iid):
        acts = RuleBasedPlanner().plan(rel, iid)
        if acts:
            return acts
        # Nothing to rotate. If the key is dead but still sitting in the file, clean it up; if it
        # cannot be attributed, plan nothing at all and let closure escalate.
        g = {r["rel"]: r for r in rel}
        lk, cred = g["leak"], g.get("owns_credential")
        if cred and not lk["still_valid"]:
            acts.append(make_action(iid, 1, "scrub_exposed_secret", lk["path"],
                                    {"service": "github", "cred_id": cred["cred"], "old_fp": lk["fp"]},
                                    summary=f"Remove the already-revoked key from {lk['path']} so scanners stop "
                                            "flagging a key that can no longer be used."))
        return acts

    def conditions(self, rel):
        return leak_conditions(rel)

    def closed_summary(self, n):
        return (f"Closed with evidence: all {n} actions were independently verified. The leaked key is rejected "
                "when used, every service that depended on it runs on a replacement and is healthy, and the key "
                "is gone from the file the scanner flagged.")

    def follow_ups(self, inc, acts):
        out = []
        g = {r["rel"]: r for r in inc.relationships}
        lk, cred = g["leak"], g.get("owns_credential")
        if cred is None:
            out.append(f"Identify the owner of the key in {lk['path']}. Rook will not revoke a credential it "
                       "cannot attribute, because it cannot tell what would break.")
            return out
        if any(a.type == "scrub_exposed_secret" and a.status.value == "verified" for a in acts):
            out.append(f"Git history of {lk['path']} still contains the leaked key. It no longer works; rewrite "
                       "history only if policy requires it.")
        if lk.get("days_exposed"):
            out.append(f"The key sat in {lk['repo']} for {lk['days_exposed']} days before anyone acted. Consider "
                       "pre-commit secret scanning so the next one is caught at commit time.")
        for a in acts:
            if a.result.get("rolled_back"):
                out.append(f"{a.target} was rolled back to the previous key after its update failed. Fix the "
                           "service, then run the incident again.")
        return out

    def declines(self, inc, acts):
        g = {r["rel"]: r for r in inc.relationships}
        lk, cred = g["leak"], g.get("owns_credential")
        if cred is None:
            return [{"what": f"Revoke or remove the key found in {lk['path']}",
                     "why": "It matches no credential in the vault, so Rook cannot tell who owns it or what "
                            "would stop working. It will not guess.",
                     "rule": "R2-ownership"}]
        if not lk["still_valid"]:
            return [{"what": f"Rotate {cred['cred']}",
                     "why": "The leaked key is already revoked, so issuing a replacement would be churn with a "
                            "production risk and no benefit.",
                     "rule": "R0-default"}]
        return []

    def impact(self, sb, inc):
        g = {r["rel"]: r for r in inc.relationships}
        cred = g.get("owns_credential")
        return [d for d in (cred["dependents"] if cred else []) if not sb.health(d)]




# ================================================================ playbook: care follow-up
#
# A clinic records that a referral was sent, a result was filed, a prescription went to the
# pharmacy. Each of those is one system saying something about work that happens somewhere else.
# Often it never happened, and nothing in the record says so. The patient goes home believing it
# is handled. Rook asks the place the work was supposed to reach, and refuses to let the record
# say "done" while anything is still missing.
#
# Rook does the chasing, not the medicine. It moves paperwork and contacts people. It never reads
# a result and decides what it means, and anything urgent goes straight to a doctor.

KIND_LABEL = {"referral": "referral", "result": "test result", "prescription": "prescription"}


def care_subject(sb):
    return sb.records.scope()


def _place(h):
    """Where this was supposed to get to, in the words a patient would use."""
    return {"referral": h["place"], "prescription": "the pharmacy",
            "result": f"{h['doctor']}, who ordered it"}[h["kind"]]


def investigate_care(sb, subject):
    """Go through everything the clinic started for a patient and ask whether it actually happened."""
    rel, unfinished = [], 0
    for oid, o in sorted(sb.records.orders().items()):
        missing = sb.handoff_gaps(oid)
        pat = sb.records.patient(o["patient"]) or {}
        doc = sb.records.clinician(o.get("ordered_by")) or {}
        res = sb.records.result(oid) or {}
        sp = o.get("specialty")
        rel.append({
            "rel": "follow_up", "order": oid, "kind": o["kind"],
            "patient": o["patient"], "patient_name": pat.get("name", o["patient"]),
            "specialty": sp, "place": SPECIALTY.get(sp, sp), "drug": o.get("drug"),
            "reason": o.get("reason", ""),
            "ordered_by": o.get("ordered_by"), "doctor": doc.get("name", o.get("ordered_by")),
            "ordered_at": o.get("ordered_at", ""), "days_waiting": _days_since(o.get("ordered_at")),
            "record_status": o.get("record_status", ""), "record_says_done": bool(o.get("loop_closed")),
            "urgent": o.get("urgency") == "critical", "finding": res.get("finding", ""),
            "missing": missing, "finished": not missing,
            "channel": sb.outreach.best_channel(o["patient"]),
            "send_channel": sb.booking.working_channel(sp) if sp else None,
            "received": sb.booking.received(oid, sp) if sp else None,
            "at_pharmacy": sb.pharmacy.has(oid) if o["kind"] == "prescription" else None})
        unfinished += bool(missing)
    info = {"name": sb.records.clinic(), "total": len(rel), "unfinished": unfinished}
    return info, rel, care_graph(rel), care_findings(rel, info)


def care_graph(rel):
    nodes, edges = [], []
    for h in rel:
        oid = h["order"]
        nodes.append({"id": oid, "kind": "credential",
                      "label": f"{KIND_LABEL[h['kind']]} for {h['patient_name']}",
                      "status": "done" if h["finished"] else f"{len(h['missing'])} thing(s) missing",
                      "detail": h["reason"]})
        who = f"patient:{h['patient']}"
        nodes.append({"id": who, "kind": "identity", "label": h["patient_name"],
                      "status": "can be reached" if h["channel"] else "no working contact", "detail": ""})
        edges.append({"from": who, "to": oid, "rel": "is waiting on"})
        dest = {"referral": f"place:{h['specialty']}", "prescription": "place:pharmacy",
                "result": f"doctor:{h['ordered_by']}"}[h["kind"]]
        reached = {"referral": h["received"], "prescription": h["at_pharmacy"],
                   "result": h["finished"]}[h["kind"]]
        nodes.append({"id": dest, "kind": "dependent", "label": _place(h),
                      "status": "has it" if reached else "never got it", "detail": ""})
        edges.append({"from": oid, "to": dest, "rel": "should have reached"})
    seen, uniq = set(), []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            uniq.append(n)
    return {"nodes": uniq, "edges": edges}


def care_findings(rel, info):
    out = [{"severity": "high" if info["unfinished"] else "info",
            "text": f"{info['unfinished']} of {info['total']} things the clinic's record calls done have not "
                    "actually happened. Each one was marked finished by the person who started it, and nobody "
                    "checked afterwards.",
            "evidence": {"checked": info["total"], "unfinished": info["unfinished"]}}]
    for h in rel:
        label, waited = KIND_LABEL[h["kind"]], h["days_waiting"]
        when = f" {waited} days ago" if waited is not None else ""
        if h["urgent"]:
            out.append({"severity": "high",
                        "text": f"{h['patient_name']}'s {label} is urgent ({h['finding']}) and no doctor has seen "
                                "it. Deciding what to do about it is a doctor's job, so Rook will alert "
                                f"{h['doctor']} and leave the rest alone.",
                        "evidence": {"order": h["order"], "finding": h["finding"]}})
            continue
        if h["finished"]:
            out.append({"severity": "info",
                        "text": f"{h['patient_name']}'s {label} really did happen. The {_place(h)} has it, "
                                "the appointment exists and she has replied. Rook checked and will not touch it.",
                        "evidence": {"order": h["order"]}})
            continue
        out.append({"severity": "high",
                    "text": f"{h['patient_name']}'s {label} was ordered{when}, and the record says "
                            f"'{h['record_status']}'. In fact: " + "; ".join(h["missing"]) + ".",
                    "evidence": {"order": h["order"], "missing": h["missing"]}})
        if h["kind"] == "referral" and not h["received"] and h["send_channel"]:
            out.append({"severity": "medium",
                        "text": f"It went to {h['sent_to'] if h.get('sent_to') else 'a channel'} the {h['place']} "
                                f"no longer uses. What they do read is {h['send_channel']}.",
                        "evidence": {"working_channel": h["send_channel"]}})
        if "the patient has not been told" in h["missing"] and not h["channel"]:
            out.append({"severity": "medium",
                        "text": f"Every phone number and address on file for {h['patient_name']} is out of date, so "
                                "there is no way to tell them. A person has to track them down.",
                        "evidence": {"patient": h["patient"]}})
    return out


class CareFollowUp:
    key = "care"
    name = "Care follow-up"
    trigger = "A check of everything the clinic says it has finished"
    contain_type, contain_label = "close_loop", "First one honestly finished after"

    def find_subject(self, sb):
        return care_subject(sb)

    def investigate(self, sb, subject):
        return investigate_care(sb, subject)

    def title(self, info, subject):
        return (f"{info['unfinished']} of {info['total']} things marked done in the record "
                "never actually happened")

    def discovery(self, rel):
        return (f"the specialist clinics, the pharmacy and the patients behind {len(rel)} records",
                [h["order"] for h in rel],
                {"checked": len(rel), "unfinished": sum(not h["finished"] for h in rel),
                 "urgent": sum(h["urgent"] for h in rel)})

    def plan(self, rel, iid):
        acts = []

        def add(t, target, deps=(), summary="", risk="low", **p):
            a = make_action(iid, len(acts) + 1, t, target, p, deps, summary, risk)
            acts.append(a)
            return a
        for h in rel:
            if h["finished"]:
                continue
            oid, steps = h["order"], []
            if h["urgent"]:
                add("notify_clinician", oid, service="records", clinician=h["ordered_by"],
                    patient=h["patient"], risk="medium",
                    summary=f"Alert {h['doctor']} straight away about {h['patient_name']}'s urgent result "
                            f"({h['finding']}). Rook does nothing else with it.")
                continue
            if h["kind"] == "referral":
                if not h["received"] and h["send_channel"]:
                    steps.append(add("resend_referral", oid, service="records", channel=h["send_channel"],
                                     patient=h["patient"], specialty=h["specialty"],
                                     summary=f"Send {h['patient_name']}'s referral to the {h['place']} again, "
                                             f"this time through {h['send_channel']}."))
                steps.append(add("book_appointment", oid, [x.id for x in steps], service="booking",
                                 patient=h["patient"], specialty=h["specialty"],
                                 summary=f"Get {h['patient_name']} an actual appointment at the {h['place']}."))
            elif h["kind"] == "prescription":
                if not h["at_pharmacy"]:
                    steps.append(add("resend_prescription", oid, service="pharmacy", patient=h["patient"],
                                     summary=f"Send {h['patient_name']}'s {h['drug']} to the pharmacy again. "
                                             "The pharmacy has no record of it."))
            elif h["kind"] == "result":
                steps.append(add("notify_clinician", oid, service="records", clinician=h["ordered_by"],
                                 patient=h["patient"],
                                 summary=f"Put {h['patient_name']}'s result in front of {h['doctor']}, who "
                                         "ordered it and has not seen it."))
            if h["channel"] and "the patient has not been told" in h["missing"]:
                steps.append(add("contact_patient", oid, [x.id for x in steps], service="outreach",
                                 patient=h["patient"], channel=h["channel"]["kind"],
                                 value=h["channel"]["value"], risk="medium",
                                 summary=f"Tell {h['patient_name']} what has been arranged, by "
                                         f"{h['channel']['kind']} on the {h['channel']['value']}, which is the one "
                                         "she still uses."))
            if steps:
                add("close_loop", oid, [x.id for x in steps], service="records", patient=h["patient"],
                    summary=f"Mark {oid} finished in the record, and only once everywhere else agrees it is.")
        return acts

    def conditions(self, rel):
        return care_conditions(rel)

    def closed_summary(self, n):
        return (f"Finished with proof: all {n} steps were checked independently. Everything the record called done "
                "was tested against the place it was supposed to reach, the ones that had not happened were put "
                "right, and the record now says done only where that is true.")

    def declines(self, inc, acts):
        out = []
        for h in inc.relationships:
            if h["rel"] != "follow_up":
                continue
            if h["urgent"]:
                out.append({"what": f"Deal with {h['patient_name']}'s urgent result itself",
                            "why": f"What an urgent result means is a doctor's decision. Rook alerted {h['doctor']} "
                                   "and will not file it, move it or mark it done on their behalf.",
                            "rule": "R6-clinical-scope"})
            if h["finished"]:
                out.append({"what": f"Change anything about {h['patient_name']}'s {KIND_LABEL[h['kind']]}",
                            "why": f"Rook checked with the {_place(h)} and it genuinely is finished. "
                                   "There is nothing to do.", "rule": "R0-default"})
            if "the patient has not been told" in h["missing"] and not h["channel"]:
                out.append({"what": f"Mark {h['patient_name']}'s {KIND_LABEL[h['kind']]} as done",
                            "why": "Every way of contacting them is out of date, so they still do not know. "
                                   "Rook will not let the record claim otherwise.",
                            "rule": "R9-truthful-record"})
        return out

    def follow_ups(self, inc, acts):
        out = []
        for h in inc.relationships:
            if h["rel"] != "follow_up":
                continue
            if h["urgent"]:
                out.append(f"{h['doctor']} has been alerted about {h['patient_name']}'s urgent result. A doctor "
                           "has to look at it and sign it off. Rook cannot do that part.")
            if "the patient has not been told" in h["missing"] and not h["channel"]:
                out.append(f"Find a way to reach {h['patient_name']}. Until someone does, they have no idea what "
                           "was arranged for them.")
        if any(h["rel"] == "follow_up" and not h["finished"] for h in inc.relationships):
            out.append("All of these were marked done by the people who started them, with nothing checking "
                       "afterwards. That gap is the thing worth fixing properly.")
        return out

    def impact(self, sb, inc):
        return []




# ================================================================ playbook: cover a doctor's absence
#
# A doctor calls in sick. Twelve people are booked in with them today and do not know yet. Moving
# that list is pure coordination: find who is affected, find who has room, move each one, tell each
# person, and make sure nobody ended up in the same slot twice or left booked with someone who is
# not coming in. It is the sort of morning a receptionist loses, and nothing about it is medical.
#
# The rule that matters: Rook will not move an appointment it cannot tell the patient about, because
# that patient would arrive at a time that no longer exists.


def cover_subject(sb):
    off = sb.schedule.off_today()
    return sb.records.scope() if off else None


def investigate_cover(sb, subject):
    """Who is affected, who could see them instead, and who can actually be told."""
    off = sb.schedule.off_today()[0]
    booked = sb.schedule.booked_with(off)
    options = sb.schedule.cover_options(off)
    pool = sorted([(d, t) for d, ts in options.items() for t in ts], key=lambda x: x[1])
    rel = [{"rel": "absence", "doctor": off, "doctor_name": sb.schedule.doctor_name(off),
            "day": DAY, "affected": len(booked), "cover_slots": len(pool),
            "covering": {sb.schedule.doctor_name(d): len(ts) for d, ts in options.items()}}]
    for aid, ap in sorted(booked.items()):
        pat = sb.records.patient(ap["patient"]) or {}
        ch = sb.outreach.best_channel(ap["patient"])
        slot = pool.pop(0) if pool else None
        rel.append({"rel": "booking", "appointment": aid, "patient": ap["patient"],
                    "patient_name": pat.get("name", ap["patient"]), "at": ap["at"],
                    "time": ap["at"][11:16], "reason": ap.get("reason", ""),
                    "channel": ch,
                    "to_doctor": slot[0] if slot else None,
                    "to_doctor_name": sb.schedule.doctor_name(slot[0]) if slot else None,
                    "to_time": slot[1] if slot else None,
                    "new_time": slot[1][11:16] if slot else None,
                    # Rook moves someone only if there is a slot and a way to tell them.
                    "movable": bool(slot and ch),
                    "why_not": (None if slot and ch else
                                "no colleague has a free slot" if not slot else
                                "no working phone number or address on file")})
    return rel[0], rel, cover_graph(rel), cover_findings(rel)


def cover_graph(rel):
    off = rel[0]
    nodes = [{"id": off["doctor"], "kind": "identity", "label": off["doctor_name"],
              "status": "off sick today", "detail": f"{off['affected']} people booked in"}]
    edges = []
    for m in (r for r in rel if r["rel"] == "booking"):
        nodes.append({"id": m["appointment"], "kind": "credential",
                      "label": f"{m['time']} · {m['patient_name']}",
                      "status": "can be moved" if m["movable"] else "stuck",
                      "detail": m["reason"]})
        edges.append({"from": off["doctor"], "to": m["appointment"], "rel": "was seeing"})
        if m["movable"]:
            nodes.append({"id": m["to_doctor"], "kind": "dependent", "label": m["to_doctor_name"],
                          "status": "in today, has room", "detail": ""})
            edges.append({"from": m["appointment"], "to": m["to_doctor"], "rel": "moves to"})
    seen, uniq = set(), []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            uniq.append(n)
    return {"nodes": uniq, "edges": edges}


def cover_findings(rel):
    off = rel[0]
    bookings = [r for r in rel if r["rel"] == "booking"]
    movable = [m for m in bookings if m["movable"]]
    stuck = [m for m in bookings if not m["movable"]]
    out = [{"severity": "high",
            "text": f"{off['doctor_name']} is off sick today. {off['affected']} people are booked in with "
                    "them and none of them know yet.",
            "evidence": {"doctor": off["doctor"], "affected": off["affected"]}},
           {"severity": "info",
            "text": "Colleagues who are in and have room: "
                    + (", ".join(f"{d} ({n} slots)" for d, n in off["covering"].items()) or "none")
                    + f". That is {off['cover_slots']} slots for {off['affected']} people.",
            "evidence": {"covering": off["covering"]}}]
    if movable:
        out.append({"severity": "info",
                    "text": f"{len(movable)} of the {off['affected']} can be moved to another doctor at a "
                            "similar time and told about it.",
                    "evidence": {"movable": [m["patient_name"] for m in movable]}})
    for m in stuck:
        out.append({"severity": "high",
                    "text": f"{m['patient_name']} ({m['time']}, {m['reason']}) cannot be sorted automatically: "
                            f"{m['why_not']}. Rook will leave the appointment where it is and hand this to "
                            "reception, because moving someone who will not hear about it is worse than "
                            "leaving it alone.",
                    "evidence": {"appointment": m["appointment"], "why_not": m["why_not"]}})
    return out


class ClinicCover:
    key = "cover"
    name = "Doctor off sick"
    trigger = "A doctor marked unavailable with patients booked in"
    contain_type, contain_label = "move_appointment", "First patient moved after"

    def find_subject(self, sb):
        return cover_subject(sb)

    def investigate(self, sb, subject):
        return investigate_cover(sb, subject)

    def title(self, info, subject):
        return f"{info['doctor_name']} is off sick: {info['affected']} appointments to move today"

    def discovery(self, rel):
        off = rel[0]
        return (f"today's list for {off['doctor_name']}, colleagues' free slots and patient contacts",
                [m["appointment"] for m in rel if m["rel"] == "booking"],
                {"affected": off["affected"], "cover_slots": off["cover_slots"],
                 "stuck": sum(1 for m in rel if m["rel"] == "booking" and not m["movable"])})

    def plan(self, rel, iid):
        acts, off = [], rel[0]

        def add(t, target, deps=(), summary="", risk="low", **p):
            a = make_action(iid, len(acts) + 1, t, target, p, deps, summary, risk)
            acts.append(a)
            return a
        for m in (r for r in rel if r["rel"] == "booking"):
            if not m["movable"]:
                continue
            mv = add("move_appointment", m["appointment"], service="schedule", patient=m["patient"],
                     from_doctor=off["doctor"], to_doctor=m["to_doctor"], to_time=m["to_time"],
                     summary=f"Move {m['patient_name']} from {m['time']} with {off['doctor_name']} to "
                             f"{m['new_time']} with {m['to_doctor_name']}.")
            add("contact_patient", m["appointment"], [mv.id], service="outreach", patient=m["patient"],
                channel=m["channel"]["kind"], value=m["channel"]["value"], risk="medium",
                summary=f"Tell {m['patient_name']} by {m['channel']['kind']} that their appointment is now "
                        f"{m['new_time']} with {m['to_doctor_name']}.")
        return acts

    def conditions(self, rel):
        return cover_conditions(rel)

    def closed_summary(self, n):
        return (f"Finished with proof: all {n} steps were checked independently. Everyone has an appointment "
                "with a doctor who is actually in, everyone has replied, nobody was put into a slot that was "
                "already taken, and nobody is left booked with the doctor who is off.")

    def declines(self, inc, acts):
        out = []
        for m in inc.relationships:
            if m["rel"] != "booking" or m["movable"]:
                continue
            out.append({"what": f"Move {m['patient_name']}'s {m['time']} appointment",
                        "why": f"{sentence(m['why_not'])}. Moving someone who will not hear about it means "
                               "they turn up to a time that no longer exists, so Rook leaves it for reception.",
                        "rule": "R9-truthful-record"})
        return out

    def follow_ups(self, inc, acts):
        stuck = [m for m in inc.relationships if m["rel"] == "booking" and not m["movable"]]
        out = [f"Reception needs to phone {m['patient_name']} about their {m['time']} appointment "
               f"({m['reason']}): {m['why_not']}." for m in stuck]
        if stuck:
            out.append(f"{len(stuck)} of today's patients are still booked with a doctor who is not coming in. "
                       "Until someone sorts those, the day is not actually covered.")
        return out

    def impact(self, sb, inc):
        return []


# ================================================================ playbook: a fixture cannot go ahead
#
# A pitch is shut on a Saturday morning and three matches are booked on it. Six clubs, three
# officials and a league secretary who otherwise spends the morning on the phone. Nothing about it
# is medical, and it is the same job as the clinic's: find what is affected, find where it can go,
# and do not tell anyone a kick-off time that is not real.
#
# The rule that matters: Rook will not move a fixture it cannot tell both clubs about, and will not
# leave a match without an official who is actually available.


def shut_pitch(sb):
    """The closure worth working: the shut pitch with the most matches on it.

    More than one can be shut on a bad weekend, and the one that matters is the one people are
    due at, not whichever happens to sort first.
    """
    shut = sb.league.closed_venues()
    return max(shut, key=lambda v: (len(sb.league.at_venue(v)), v)) if shut else None


def fixtures_subject(sb):
    return sb.league.scope() if shut_pitch(sb) else None


def investigate_fixtures(sb, subject):
    """What is at the closed pitch, where each match could go, who can run it, and who can be told."""
    closed = shut_pitch(sb)
    affected = sb.league.at_venue(closed)
    slots = sb.league.open_slots()
    spares = sb.league.spare_officials()
    rel = [{"rel": "closure", "venue": closed, "venue_name": sb.league.venue_name(closed),
            "day": MATCH_DAY, "affected": len(affected), "open_slots": len(slots),
            "elsewhere": {sb.league.venue_name(v): len([t for vv, t in slots if vv == v])
                          for v, _ in slots}}]
    for fid, x in sorted(affected.items()):
        slot = slots.pop(0) if slots else None
        official, needs_official = x["official"], not sb.league.official_available(x["official"])
        if needs_official:
            official = spares.pop(0) if spares else None
        contacts = {t: sb.league.best_contact(t) for t in (x["home"], x["away"])}
        unreachable = [sb.league.team_name(t) for t, c in contacts.items() if c is None]
        rel.append({"rel": "fixture", "fixture": fid, "grade": x["grade"],
                    "home": x["home"], "home_name": sb.league.team_name(x["home"]),
                    "away": x["away"], "away_name": sb.league.team_name(x["away"]),
                    "at": x["at"], "time": x["at"][11:16],
                    "to_venue": slot[0] if slot else None,
                    "to_venue_name": sb.league.venue_name(slot[0]) if slot else None,
                    "to_time": slot[1] if slot else None,
                    "new_time": slot[1][11:16] if slot else None,
                    "official": official, "needs_official": needs_official,
                    "official_name": sb.league.official_name(official) if official else None,
                    "was_official_name": sb.league.official_name(x["official"]),
                    "unreachable": unreachable,
                    # A match moves only if it has somewhere to go, someone to run it, and two
                    # clubs that can be told.
                    "movable": bool(slot and official and not unreachable),
                    "why_not": (None if slot and official and not unreachable else
                                "no other pitch has a free slot" if not slot else
                                "no official is available to run it" if not official else
                                f"no working contact for {unreachable[0]}")})
    return rel[0], rel, fixtures_graph(rel), fixtures_findings(rel)


def fixtures_graph(rel):
    shut = rel[0]
    nodes = [{"id": shut["venue"], "kind": "identity", "label": shut["venue_name"],
              "status": "closed today", "detail": f"{shut['affected']} matches booked on it"}]
    edges = []
    for m in (r for r in rel if r["rel"] == "fixture"):
        nodes.append({"id": m["fixture"], "kind": "credential",
                      "label": f"{m['time']} \u00b7 {m['home_name']} v {m['away_name']}",
                      "status": "can be moved" if m["movable"] else "stuck", "detail": m["grade"]})
        edges.append({"from": shut["venue"], "to": m["fixture"], "rel": "was on"})
        if m["movable"]:
            nodes.append({"id": m["to_venue"], "kind": "dependent", "label": m["to_venue_name"],
                          "status": "open, has a slot", "detail": ""})
            edges.append({"from": m["fixture"], "to": m["to_venue"], "rel": "moves to"})
    seen, uniq = set(), []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            uniq.append(n)
    return {"nodes": uniq, "edges": edges}


def fixtures_findings(rel):
    shut = rel[0]
    games = [r for r in rel if r["rel"] == "fixture"]
    movable = [m for m in games if m["movable"]]
    stuck = [m for m in games if not m["movable"]]
    out = [{"severity": "high",
            "text": f"{shut['venue_name']} is closed today and {shut['affected']} matches are booked on "
                    "it. None of the clubs know yet.",
            "evidence": {"venue": shut["venue"], "affected": shut["affected"]}},
           {"severity": "info",
            "text": "Pitches that are open and have a slot: "
                    + (", ".join(f"{v} ({n})" for v, n in shut["elsewhere"].items()) or "none")
                    + f". That is {shut['open_slots']} slots for {shut['affected']} matches.",
            "evidence": {"elsewhere": shut["elsewhere"]}}]
    for m in movable:
        if m["needs_official"]:
            out.append({"severity": "info",
                        "text": f"{m['home_name']} v {m['away_name']} has {m['was_official_name']} down to "
                                f"referee, who is not available. {m['official_name']} is on the spare list "
                                "and can take it.",
                        "evidence": {"fixture": m["fixture"], "official": m["official"]}})
    if movable:
        out.append({"severity": "info",
                    "text": f"{len(movable)} of the {shut['affected']} can be moved to another pitch and "
                            "both clubs told.",
                    "evidence": {"movable": [m["fixture"] for m in movable]}})
    for m in stuck:
        out.append({"severity": "high",
                    "text": f"{m['home_name']} v {m['away_name']} ({m['time']}, {m['grade']}) cannot be "
                            f"sorted automatically: {m['why_not']}. Rook will leave it alone and hand it to "
                            "the league secretary, because a match nobody can be told about is worse than a "
                            "match everyone knows is off.",
                    "evidence": {"fixture": m["fixture"], "why_not": m["why_not"]}})
    return out


class Fixtures:
    key = "fixtures"
    name = "Fixture cannot go ahead"
    trigger = "A pitch closed with matches booked on it"
    contain_type, contain_label = "move_fixture", "First match moved after"

    def find_subject(self, sb):
        return fixtures_subject(sb)

    def investigate(self, sb, subject):
        return investigate_fixtures(sb, subject)

    def title(self, info, subject):
        return f"{info['venue_name']} is closed: {info['affected']} matches to move today"

    def discovery(self, rel):
        shut = rel[0]
        return (f"today's fixtures at {shut['venue_name']}, free slots at the other pitches, the officials "
                "on the list and each club's contact",
                [m["fixture"] for m in rel if m["rel"] == "fixture"],
                {"affected": shut["affected"], "open_slots": shut["open_slots"],
                 "stuck": sum(1 for m in rel if m["rel"] == "fixture" and not m["movable"])})

    def plan(self, rel, iid):
        acts, shut = [], rel[0]

        def add(t, target, deps=(), summary="", risk="low", **p):
            a = make_action(iid, len(acts) + 1, t, target, p, deps, summary, risk)
            acts.append(a)
            return a
        for m in (r for r in rel if r["rel"] == "fixture"):
            if not m["movable"]:
                continue
            teams = [m["home"], m["away"]]
            mv = add("move_fixture", m["fixture"], service="league", teams=teams,
                     from_venue=shut["venue"], to_venue=m["to_venue"], to_time=m["to_time"],
                     summary=f"Move {m['home_name']} v {m['away_name']} from {m['time']} at "
                             f"{shut['venue_name']} to {m['new_time']} at {m['to_venue_name']}.")
            deps = [mv.id]
            if m["needs_official"]:
                off = add("assign_official", m["fixture"], [mv.id], service="league", teams=teams,
                          official=m["official"],
                          summary=f"Put {m['official_name']} on {m['home_name']} v {m['away_name']}, because "
                                  f"{m['was_official_name']} is not available today.")
                deps.append(off.id)
            add("tell_teams", m["fixture"], deps, service="league", teams=teams, risk="medium",
                summary=f"Tell {m['home_name']} and {m['away_name']} that their match is now {m['new_time']} "
                        f"at {m['to_venue_name']}, with {m['official_name']} refereeing.")
        return acts

    def conditions(self, rel):
        return fixtures_conditions(rel)

    def closed_summary(self, n):
        return (f"Finished with proof: all {n} steps were checked independently. Every match that could be "
                "moved is on a pitch that is open, with an official who is available, and both clubs have "
                "answered. Nothing is left on the closed pitch, and no two matches share a pitch and a "
                "kick-off time.")

    def declines(self, inc, acts):
        out = []
        for m in inc.relationships:
            if m["rel"] != "fixture" or m["movable"]:
                continue
            out.append({"what": f"Move {m['home_name']} v {m['away_name']} ({m['time']})",
                        "why": f"{sentence(m['why_not'])}. Moving a match that one of the clubs will not "
                               "hear about means a team travelling to a pitch with nobody on it, so Rook "
                               "leaves it for the league secretary.",
                        "rule": "R9-truthful-record"})
        return out

    def follow_ups(self, inc, acts):
        stuck = [m for m in inc.relationships if m["rel"] == "fixture" and not m["movable"]]
        out = [f"The league secretary needs to call {m['home_name']} and {m['away_name']} about the "
               f"{m['time']} {m['grade']} match: {m['why_not']}." for m in stuck]
        if stuck:
            out.append(f"{len(stuck)} match(es) are still down for a pitch that is shut. Until someone sorts "
                       "those, the morning is not actually covered.")
        return out

    def impact(self, sb, inc):
        return []


PLAYBOOKS = {p.key: p for p in (Offboarding(), Outage(), LeakedSecret(), CareFollowUp(), ClinicCover(),
                                Fixtures())}


def playbook_for(scenario=None, key=None):
    return PLAYBOOKS[key or playbook_of(scenario)]
