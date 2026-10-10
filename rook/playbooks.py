"""Playbooks: the incident types Rook can resolve.

The engine (plan -> authorize -> execute -> reconcile -> verify -> close on evidence) is the same for
every incident. A playbook supplies what differs: how an incident is triggered, what Rook reads to
investigate it, the remediation it plans, and the closure checks that must hold before it is closed.

- offboarding: someone left, but their access and keys live on (access management)
- outage: a production service is failing after a change (cloud / IT incident)
"""
from .domain import Action
from .sandbox import playbook_of
from .verification import build_conditions, outage_conditions


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

    def impact(self, sb, inc):
        st = next(r for r in inc.relationships if r["rel"] == "service_state")
        svc = st["service"]
        return ([f"cloud:{svc}"] if not sb.cloud.service_healthy(svc) else []) + \
            [c for c in sb.callers_of(svc) if not sb.caller_healthy(c, svc)]


PLAYBOOKS = {p.key: p for p in (Offboarding(), Outage())}


def playbook_for(scenario=None, key=None):
    return PLAYBOOKS[key or playbook_of(scenario)]
