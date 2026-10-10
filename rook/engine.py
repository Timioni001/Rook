"""Rook: a bounded, tool-using incident-response agent with Verified Closure.

INVESTIGATE -> DEFINE CLOSURE -> PLAN (dependency graph) -> AUTHORIZE -> EXECUTE -> VERIFY
-> CHECKPOINT -> RECOVER / ESCALATE -> CLOSE ONLY ON EVIDENCE.

All state lives in SQLite, so a run can stop at any point (crash, approval wait, cancel) and be
resumed by a new process from the last checkpoint.
"""
import json, os, time, uuid
from .domain import Action, Condition, Incident, IncidentStatus as IS, Status, fp
from .sandbox import Transient, Permanent, Timeout
from . import policy
from .verification import applied, build_conditions, evaluate, verify_action
from .obs import log, span

S = Status
RUNNABLE = {S.authorized, S.retry_pending, S.executing, S.executed, S.unknown}
UNRESOLVED_BAD = {S.failed, S.blocked, S.unknown}


TOOL_DOCS = {
    "disable_account": "Disable a user account on a connected service (sandbox)",
    "issue_replacement": "Create a new version of a credential in the vault; old version stays valid",
    "update_dependent": "Point an application or cloud service at the newest credential version",
    "revoke_credential": "Permanently revoke one credential version in the vault",
    "scrub_exposed_secret": "Replace a leaked key in a tracked file with a placeholder",
}


class SimulatedCrash(BaseException):      # BaseException so no handler swallows it
    ...


class RunInProgress(Exception):
    ...


# ---------------------------------------------------------------- investigation

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


class LLMPlanner:
    """Model proposes from fingerprint-only observations; ordering and policy are enforced in code."""
    def __init__(self):
        self.fallback = RuleBasedPlanner()

    def plan(self, rel, iid):
        try:
            import anthropic
            m = anthropic.Anthropic().messages.create(
                model=os.getenv("ROOK_MODEL", "claude-sonnet-5-5"), max_tokens=1500,
                system=("You plan credential incident remediation. Return ONLY a JSON list of "
                        "{type,target,params,summary}. Types: disable_account (params.service github|cloud|pm), "
                        "issue_replacement (target cred id, params.service='vault'), update_dependent (target "
                        "'app:x' or 'cloud:y', params.service app|cloud, params.cred_id), revoke_credential "
                        "(target cred id, params.service='vault'). Secrets are fingerprints."),
                messages=[{"role": "user", "content": json.dumps(rel)}])
            raw = json.loads(m.content[0].text)
            by_cred = {r["cred"]: r for r in rel if r["rel"] == "owns_credential"}
            acts = []
            for x in raw:
                if x.get("type") not in policy.ALLOWED:
                    continue
                p = dict(x.get("params", {}))
                cred = x["target"] if x["type"] in ("issue_replacement", "revoke_credential") else p.get("cred_id")
                if cred in by_cred:                         # observed truth overrides model input
                    p.update(old_fp=by_cred[cred]["fp"], old_version=by_cred[cred]["version"])
                    if x["type"] == "revoke_credential":
                        p.update(cred_id=cred, version=by_cred[cred]["version"])
                acts.append(make_action(iid, len(acts) + 1, x["type"], x["target"], p,
                                        summary=x.get("summary", ""),
                                        risk="high" if x["type"] in policy.NEEDS_APPROVAL else "low"))
            return acts or self.fallback.plan(rel, iid)
        except Exception:
            return self.fallback.plan(rel, iid)


def enforce_order(plan):
    """Add the dependency edges safety requires (whatever the planner said) and topologically sort.

    issue_replacement -> update_dependent(s) -> revoke_credential, per credential.
    """
    by_id = {a.id: a for a in plan}
    for a in plan:
        cred = a.target if a.type in ("issue_replacement", "revoke_credential") else a.params.get("cred_id")
        need = []
        if a.type == "update_dependent":
            need = [x.id for x in plan if x.type == "issue_replacement" and x.target == cred]
        if a.type == "revoke_credential":
            need = [x.id for x in plan if x.type in ("issue_replacement", "update_dependent")
                    and (x.target == cred or x.params.get("cred_id") == cred)]
        if a.type == "scrub_exposed_secret":             # only touch the file once the key is dead
            need = [x.id for x in plan if x.type == "revoke_credential" and x.target == cred]
        a.depends_on = sorted(set(d for d in a.depends_on if d in by_id) | set(need))
    order, seen, temp = [], set(), set()

    def visit(a):
        if a.id in seen:
            return
        if a.id in temp:
            raise ValueError("dependency cycle in plan")
        temp.add(a.id)
        for d in a.depends_on:
            visit(by_id[d])
        temp.discard(a.id)
        seen.add(a.id)
        order.append(a)
    for a in plan:
        visit(a)
    return order


# ---------------------------------------------------------------- engine

class Engine:
    def __init__(self, store, sb, planner=None, max_steps=200, max_retries=3,
                 sleep=time.sleep, crash_after=None, step_delay=0.0):
        self.store, self.sb = store, sb
        self.planner = planner or (LLMPlanner() if os.getenv("ROOK_PLANNER") == "llm" else RuleBasedPlanner())
        self.max_steps, self.max_retries = max_steps, max_retries
        self.sleep, self.crash_after, self.step_delay = sleep, crash_after, step_delay
        self.executions = 0
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    # ---- INVESTIGATE -> DEFINE CLOSURE -> PLAN -> AUTHORIZE ----
    def start(self, subject=None, org="acme", created_by="system", scenario=None, extra_actions=()):
        iid = "inc-" + uuid.uuid4().hex[:8]
        with span("incident.start", session=iid, user=created_by, user_meta={"org": org},
                  incident=iid, org=org, scenario=scenario or "") as root:
            if subject is None:                       # trigger: completed offboarding tickets
                done = self.sb.pm.completed_offboardings()
                subject = next(iter(done.values()))["subject"] if done else None
                if subject is None:
                    raise ValueError("no completed offboarding to investigate")
            with span("investigate", incident=iid) as sp:
                person, rel, graph, finds = investigate(self.sb, subject)
                sp.set(accounts=sum(r["rel"] == "has_account" for r in rel),
                       active_credentials=sum(r["rel"] == "owns_credential" and r["status"] == "active" for r in rel))
            with span("discover.dependencies", incident=iid) as sp:
                deps = [d for r in rel if r["rel"] == "owns_credential" for d in r["dependents"]]
                sp.retriever("config scan for " + ", ".join(r["fp"] for r in rel if r["rel"] == "owns_credential"),
                             deps)
                sp.set(dependents=len(deps), unrecorded=sum(len(r.get("unrecorded_dependents", [])) for r in rel
                                                            if r["rel"] == "owns_credential"))
            inc = Incident(id=iid, org=org, created_by=created_by, subject=subject, scenario=scenario or "custom",
                           title=f"Active credential after offboarding: {person.get('name', subject)}",
                           relationships=rel, graph=graph, findings=finds,
                           exposure=" ".join(f["text"] for f in finds),
                           severity="high" if any(f["severity"] == "high" for f in finds) else "medium")
            self.store.save_incident(inc)
            self.store.audit(iid, "investigated", {"relationships": rel, "findings": [f["text"] for f in finds]})

            conds = build_conditions(rel)                  # defined BEFORE any remediation
            self.store.save_conditions(iid, conds)
            self.store.audit(iid, "closure_conditions_defined", {"conditions": [c.id for c in conds]})

            try:
                inc.ticket = self.sb.pm.open_ticket(inc.title, subject, f"{iid}:ticket")["ticket"]
                self.store.audit(iid, "ticket_opened", {"ticket": inc.ticket})
            except (Transient, Timeout, Permanent) as e:   # tracking is best effort, never blocks containment
                self.store.audit(iid, "ticket_open_failed", {"error": type(e).__name__})

            with span("plan", incident=iid) as sp:
                plan = self.planner.plan(rel, iid) + list(extra_actions)
                plan = enforce_order(plan)
                sp.set(actions=len(plan), planner=type(self.planner).__name__)
            # stable ids in execution order; references rewritten accordingly
            rename = {a.id: f"{iid}-a{i+1}" for i, a in enumerate(plan)}
            seen = set()
            for i, a in enumerate(plan):
                a.id, a.incident_id = rename[a.id], iid
                a.depends_on = [rename[d] for d in a.depends_on]
                a.idem_key = f"{iid}:{a.type}:{a.params.get('service','')}:{a.target}"
                a.max_retries = self.max_retries
            for i, a in enumerate(plan):
                with span("policy.decide", incident=iid, action=a.id, action_type=a.type, target=a.target) as sp:
                    if a.idem_key in seen:
                        decision, reason, rule = "blocked", "Duplicate of another planned action.", "R6-duplicate"
                    else:
                        decision, reason, rule = policy.decide(a, inc, self.sb, plan)
                    sp.set(decision=decision, rule=rule)
                    sp.guardrail(f"{a.type} {a.target}", decision != "blocked", f"{decision} ({rule}): {reason}")
                seen.add(a.idem_key)
                a.policy = {"decision": decision, "reason": reason, "rule": rule}
                a.move({"authorized": S.authorized, "needs_approval": S.needs_approval}.get(decision, S.blocked))
                self.store.add_action(a, i)
                self.store.audit(iid, "policy_" + decision, {"action": a.id, "type": a.type, "target": a.target,
                                                             "reason": reason, "rule": rule})
                if decision == "blocked":
                    self.store.audit(iid, "escalated", {"action": a.id, "reason": reason})
            self.store.checkpoint(iid, "planned", {"statuses": {a.id: a.status.value for a in plan}})
            inc.status = IS.ready.value         # approval is asked for when the run reaches that step
            self.store.save_incident(inc)
            root.set(subject=subject, actions=len(plan), status=inc.status)
        return inc

    # ---- human approval (policy re-checked; approver identity comes from the caller's principal) ----
    def approve(self, iid, action_id, principal):
        a = self._action(iid, action_id)
        if a.status != S.needs_approval:
            raise ValueError(f"{action_id} is {a.status.value}, not awaiting approval")
        inc = self.store.incident(iid)
        approval = {"by": principal.id, "roles": list(principal.roles), "org": principal.org}
        with span("approval.decide", session=iid, user=principal.id, user_meta={"org": principal.org},
                  incident=iid, action=action_id, approver=principal.id) as sp:
            decision, reason, rule = policy.decide(a, inc, self.sb, self.store.actions(iid), approval=approval)
            sp.set(decision=decision)
            sp.guardrail(f"approve {a.type} {a.target} by {principal.id}", decision == "authorized", reason)
        if decision == "authorized":
            a.move(S.authorized)
            a.policy = {"decision": "authorized", "reason": reason, "rule": rule, "approval": approval}
            self.store.approval(iid, a.id, "approved", principal.id, {"reason": reason})
            self.store.audit(iid, "approval_granted", {"action": a.id, "by": principal.id})
        else:
            self.store.approval(iid, a.id, "refused_by_policy", principal.id, {"reason": reason})
            self.store.audit(iid, "approval_rejected_by_policy", {"action": a.id, "by": principal.id, "reason": reason})
            raise PermissionError(reason)
        self.store.save_action(a)
        return a

    def reject(self, iid, action_id, principal, note=""):
        a = self._action(iid, action_id)
        if a.status != S.needs_approval:
            raise ValueError(f"{action_id} is {a.status.value}, not awaiting approval")
        a.move(S.blocked)
        a.policy = {**a.policy, "decision": "blocked", "reason": f"Rejected by {principal.id}. {note}".strip()}
        self.store.save_action(a)
        self.store.approval(iid, a.id, "rejected", principal.id, {"note": note[:500]})
        self.store.audit(iid, "approval_rejected", {"action": a.id, "by": principal.id})
        return a

    def _action(self, iid, action_id):
        a = next((x for x in self.store.actions(iid) if x.id == action_id), None)
        if a is None:
            raise KeyError(action_id)
        return a

    # ---- EXECUTE -> VERIFY -> CHECKPOINT -> CONTINUE OR RECOVER (resumable from the DB) ----
    def run(self, iid):
        owner = uuid.uuid4().hex
        if not self.store.acquire_run(iid, owner):
            raise RunInProgress(iid)
        try:
            return self._run(iid)
        finally:
            self.store.release_run(iid, owner)

    def _run(self, iid):
        steps = 0
        inc = self.store.incident(iid)
        with span("incident.run", session=iid, user=inc.created_by, user_meta={"org": inc.org},
                  incident=iid) as root:
            acts = self.store.actions(iid)
            inflight = [a.id for a in acts if a.status in (S.executing, S.executed, S.unknown)]
            if inflight:
                cp = self.store.last_checkpoint(iid)
                with span("checkpoint.restore", incident=iid, checkpoint=cp["n"] if cp else 0,
                          inflight=len(inflight)):
                    log("resuming from checkpoint {checkpoint}", checkpoint=cp["n"] if cp else None,
                        in_flight=",".join(inflight))
                    self.store.audit(iid, "checkpoint_restored", {"checkpoint": cp["n"] if cp else None,
                                                                  "label": cp["label"] if cp else None,
                                                                  "in_flight": inflight})
            inc.status = IS.remediating.value
            self.store.save_incident(inc)
            while steps < self.max_steps and not self.cancelled:
                acts = self.store.actions(iid)
                by_id = {a.id: a for a in acts}
                before = {a.id: (a.status, a.retries) for a in acts}
                for a in acts:
                    if self.cancelled or steps >= self.max_steps:
                        break
                    if a.status not in RUNNABLE and a.status != S.needs_approval:
                        continue
                    deps = [by_id[d] for d in a.depends_on]
                    bad = [d for d in deps if d.status in UNRESOLVED_BAD]
                    if a.status == S.needs_approval and not bad:
                        continue                          # waits for a person
                    if bad and a.status in (S.authorized, S.retry_pending, S.needs_approval):
                        a.move(S.blocked)
                        a.policy = {**a.policy, "decision": "blocked", "rule": "R4-safe-order",
                                    "reason": "Not run because " + ", ".join(f"{d.id} ({d.type}) is {d.status.value}"
                                                                             for d in bad) + "."}
                        self.store.save_action(a)
                        self.store.audit(iid, "blocked_by_dependency", {"action": a.id, "waiting_on": [d.id for d in bad]})
                        continue
                    if not all(d.status == S.verified for d in deps):
                        continue                          # waiting (e.g. on approval or a sibling step)
                    while a.status in RUNNABLE and steps < self.max_steps and not self.cancelled:
                        steps += 1
                        halt = self._step(a)
                        self.store.save_action(a)
                        self.store.checkpoint(iid, "step", {"step": steps, "action": a.id, "status": a.status.value,
                                                            "statuses": {x.id: (a if x.id == a.id else x).status.value
                                                                         for x in acts}})
                        by_id[a.id] = a
                        if self.step_delay:
                            time.sleep(self.step_delay)
                        if halt:
                            break
                after = {a.id: (a.status, a.retries) for a in self.store.actions(iid)}
                if after == before:
                    break
            for a in self.store.actions(iid):
                if a.status in (S.failed, S.unknown):
                    self.store.audit(iid, "escalated", {"action": a.id, "status": a.status.value,
                                                        "reason": a.result.get("error", "outcome could not be established")})
            if self.cancelled:
                self.store.audit(iid, "cancelled", {})
            rep = self.finalize(iid)
            root.set(status=rep["status"], steps=steps)
            return rep

    def _step(self, a):
        iid = a.incident_id
        attempt = a.retries + 1
        if a.status in (S.executing, S.unknown):
            # outcome uncertain: inspect real state BEFORE any new mutation
            with span("reconcile", incident=iid, action=a.id, action_type=a.type, attempt=a.retries) as sp:
                landed = applied(self.sb, a)
                sp.set(applied=landed)
                log("inspected live state for {action}: applied={applied}", action=a.id, applied=str(landed))
            if landed is True:
                ok, ev = verify_action(self.sb, a)
                a.evidence = ev
                if ok is True:
                    a.move(S.verified)
                    self.store.audit(iid, "reconciled_verified", {"action": a.id, "evidence": ev})
                elif ok is False:
                    a.move(S.failed)
                    a.result = {**a.result, "error": "Change landed but independent verification failed."}
                    self.store.audit(iid, "reconciled_but_verification_failed", {"action": a.id, "evidence": ev})
                    if a.type == "update_dependent":
                        self._compensate(a)
                else:
                    a.move(S.unknown)
                    self.store.audit(iid, "reconcile_inconclusive", {"action": a.id, "evidence": ev})
                    return True
            elif landed is False:
                if a.retries > a.max_retries:
                    a.move(S.failed)
                    a.result = {**a.result, "error": f"Gave up after {a.retries} failed attempts."}
                    self.store.audit(iid, "failed_retries_exhausted", {"action": a.id, "attempts": a.retries})
                else:
                    a.move(S.retry_pending)
                    self.store.audit(iid, "reconciled_not_applied", {"action": a.id, "safe_to_retry": True})
            else:
                a.move(S.unknown)
                self.store.audit(iid, "reconcile_inconclusive", {"action": a.id})
                return True
            return False

        if a.status in (S.authorized, S.retry_pending):
            inc = self.store.incident(iid)
            with span("policy.recheck", incident=iid, action=a.id, action_type=a.type) as sp:
                decision, reason, rule = policy.decide(a, inc, self.sb, self.store.actions(iid),
                                                       approval=a.policy.get("approval"))
                sp.set(decision=decision, rule=rule)
                sp.guardrail(f"pre-execution check {a.type} {a.target}", decision == "authorized", reason)
            if decision != "authorized":
                a.move(S.blocked)
                a.policy = {**a.policy, "decision": "blocked", "reason": reason, "rule": rule}
                self.store.audit(iid, "policy_recheck_blocked", {"action": a.id, "reason": reason})
                return True
            a.move(S.executing)
            self.store.save_action(a)
            self.store.audit(iid, "executing", {"action": a.id, "attempt": attempt})
            try:
                with span("execute", incident=iid, action=a.id, action_type=a.type, target=a.target,
                          adapter=a.params.get("service"), attempt=attempt) as sp:
                    sp.tool(f"{a.params.get('service')}.{a.type}", TOOL_DOCS.get(a.type, a.type),
                            {"target": a.target, "idempotency_key": a.idem_key, "attempt": attempt})
                    a.result = self._exec(a)
                    sp.set(outcome="ok", replayed=bool(a.result.get("replayed")))
                self.store.tool_call(iid, a.id, attempt, "ok", a.result)
                self.executions += 1
                if self.crash_after is not None and self.executions >= self.crash_after:
                    raise SimulatedCrash()    # after mutation, before status is persisted
                a.move(S.executed)
                self.store.audit(iid, "executed", {"action": a.id, "result": a.result})
            except (Transient, Timeout) as e:
                a.retries += 1
                kind = "timeout" if isinstance(e, Timeout) else "transient"
                a.result = {"error": f"{kind}: {e}"}
                a.move(S.unknown)
                log("{action} attempt {attempt} failed ({kind}); checkpointing before inspecting state",
                    level="warning", action=a.id, attempt=attempt, kind=kind)
                self.store.tool_call(iid, a.id, attempt, kind, {"error": str(e)})
                self.store.audit(iid, f"{kind}_failure", {"action": a.id, "attempt": attempt, "error": str(e),
                                                          "next": "checkpoint, then inspect real state before retrying"})
                self.sleep(0.05 * 2 ** a.retries)
            except Permanent as e:
                a.move(S.failed)
                a.result = {"error": str(e)}
                self.store.tool_call(iid, a.id, attempt, "permanent", {"error": str(e)})
                self.store.audit(iid, "permanent_failure", {"action": a.id, "error": str(e)})
            except Exception as e:
                a.move(S.failed)
                a.result = {"error": type(e).__name__}
                self.store.tool_call(iid, a.id, attempt, "error", {"error": type(e).__name__})
                self.store.audit(iid, "unexpected_failure", {"action": a.id, "error": type(e).__name__})
            return False

        if a.status == S.executed:
            with span("verify", incident=iid, action=a.id, action_type=a.type) as sp:
                ok, ev = verify_action(self.sb, a)
                sp.set(result="pass" if ok else "fail" if ok is False else "inconclusive")
                sp.guardrail(f"independent check of {a.type} {a.target}", ok is True, json.dumps(ev))
            a.evidence = ev
            if ok is True:
                a.move(S.verified)
            elif ok is False:
                a.move(S.failed)
                a.result = {**a.result, "error": "The tool reported success but independent verification failed."}
            else:
                a.move(S.unknown)
            self.store.audit(iid, "verification_" + a.status.value, {"action": a.id, "evidence": ev})
            if a.status == S.failed and a.type == "update_dependent":
                self._compensate(a)
        return False

    def _exec(self, a):
        p = a.params
        if a.type == "disable_account":
            return self.sb.account_service(p["service"]).disable(a.target, a.idem_key)
        if a.type == "issue_replacement":
            return self.sb.vault.issue_replacement(a.target, a.idem_key)
        if a.type == "update_dependent":
            return self.sb.update_dependent(a.target, p["cred_id"], a.idem_key)
        if a.type == "revoke_credential":
            return self.sb.vault.revoke(a.target, p["version"], a.idem_key)
        if a.type == "scrub_exposed_secret":
            return self.sb.github.scrub_secret(a.target, p["old_fp"], a.idem_key)
        raise Permanent("unsupported action")

    # ---- compensation: undo a dependent update that broke the service ----
    def _compensate(self, a):
        iid = a.incident_id
        inc = self.store.incident(iid)
        ok, reason = policy.may_compensate(self.sb, a, inc)
        if not ok:
            self.store.audit(iid, "rollback_skipped", {"action": a.id, "reason": reason})
            return
        with span("rollback", incident=iid, action=a.id, target=a.target) as sp:
            sp.tool(f"{a.params.get('service')}.restore_dependent", "Put a service back on its previous, still-valid key",
                    {"target": a.target, "version": a.params["old_version"]})
            try:
                res = self.sb.restore_dependent(a.target, a.params["cred_id"], a.params["old_version"],
                                                f"{a.idem_key}:rollback")
            except (Transient, Timeout, Permanent) as e:
                self.store.tool_call(iid, a.id, a.retries + 1, "rollback_failed", {"error": str(e)})
                self.store.audit(iid, "rollback_failed", {"action": a.id, "error": str(e)})
                sp.guardrail(f"rollback {a.target}", False, str(e))
                return
            healthy = self.sb.health(a.target)
            sp.guardrail(f"rollback {a.target} restores service", healthy, json.dumps({"healthy": healthy}))
        self.store.tool_call(iid, a.id, a.retries + 1, "rollback_ok", res)
        a.result = {**a.result, "rolled_back": True, "healthy_after_rollback": healthy}
        self.store.audit(iid, "rolled_back", {"action": a.id, "target": a.target, "reason": reason,
                                              "healthy_after_rollback": healthy})

    # ---- Verified Closure: live re-observation against pre-defined conditions ----
    def report(self, iid, live=False):
        inc = self.store.incident(iid)
        acts = self.store.actions(iid)
        stored = self.store.conditions(iid)
        conds = evaluate(self.sb, stored) if live else stored
        mandatory = [c for c in conds if c.mandatory]
        events = self.store.audit_events(iid)
        names = [e["event"] for e in events]
        first_exec = names.index("executing") if "executing" in names else len(names)
        inv = {
            "closure_conditions_defined": bool(stored),
            "conditions_defined_before_remediation": "closure_conditions_defined" in names[:first_exec],
            "no_inconclusive_conditions": bool(stored) and all(c.result is not None for c in mandatory),
            "all_mandatory_conditions_pass": bool(stored) and all(c.result is True for c in mandatory),
            "all_actions_verified": bool(acts) and all(a.status == S.verified for a in acts),
            "audit_chain_intact": self.store.verify_chain()[0],
        }
        closed = all(inv.values())
        bad = [c.id for c in conds if c.mandatory and c.result is not True]
        unresolved = [{"action": a.id, "type": a.type, "target": a.target, "status": a.status.value,
                       "reason": a.policy.get("reason") if a.status in (S.blocked, S.needs_approval)
                       else a.result.get("error", "not run yet")}
                      for a in acts if a.status != S.verified]
        calls = self.store.tool_calls(iid)
        by_id = {a.id: a for a in acts}
        dead_at = next((e["ts"] for e in events if e["event"] in ("verification_verified", "reconciled_verified")
                        and by_id.get(e["data"].get("action")) is not None
                        and by_id[e["data"]["action"]].type == "revoke_credential"), None)
        if inc.status in (IS.ready.value, IS.investigating.value) and not calls:
            status = inc.status
        elif closed:
            status = IS.closed_verified.value
        elif any(a.status in UNRESOLVED_BAD for a in acts) or (bad and all(c.result is not None for c in mandatory)
                                                               and all(a.status == S.verified for a in acts)):
            status = IS.escalated.value
        elif any(a.status == S.needs_approval for a in acts):
            status = IS.awaiting_approval.value
        else:
            status = IS.open.value
        return {
            "incident": inc.model_dump(mode="json"),
            "status": status,
            "summary": summarize(inc, acts, status, bad),
            "exposure": inc.exposure,
            "invariants": inv,
            "conditions": [c.model_dump(mode="json") for c in conds],
            "actions": [{"id": a.id, "type": a.type, "target": a.target, "service": a.params.get("service"),
                         "status": a.status.value,
                         "depends_on": a.depends_on, "summary": a.summary, "risk": a.risk,
                         "retries": a.retries, "policy": a.policy, "result": a.result,
                         "evidence": a.evidence} for a in acts],
            "approvals": self.store.approvals(iid),
            "follow_ups": follow_ups(inc, acts),
            "tool_calls": calls,
            "unresolved": unresolved,
            "closure_blocked_reason": None if closed else blocked_reason(inv, bad, unresolved),
            "metrics": {"tool_calls": len(calls),
                        "failed_tool_calls": sum(c["outcome"] not in ("ok", "rollback_ok") for c in calls),
                        "retries": sum(a.retries for a in acts),
                        "checkpoints": len(self.store.checkpoints(iid)),
                        "audit_events": len(events),
                        "rollbacks": sum(1 for a in acts if a.result.get("rolled_back")),
                        "seconds_until_old_key_dead": round(dead_at - inc.created_at, 1) if dead_at else None,
                        "seconds_until_closed": round(inc.closed_at - inc.created_at, 1) if inc.closed_at else None},
        }

    def finalize(self, iid):
        with span("closure.evaluate", incident=iid) as sp:
            rep = self.report(iid, live=True)
            sp.set(status=rep["status"], passed=sum(c["result"] is True for c in rep["conditions"]),
                   total=len(rep["conditions"]))
            sp.guardrail("Verified Closure: " + ", ".join(c["id"] for c in rep["conditions"]),
                         rep["status"] == IS.closed_verified.value, rep["closure_blocked_reason"] or rep["summary"])
        self.store.save_conditions(iid, [Condition(**c) for c in rep["conditions"]])
        inc = self.store.incident(iid)
        inc.status = rep["status"]
        if rep["status"] == IS.closed_verified.value:
            inc.closed_at = inc.closed_at or time.time()
            rep["metrics"]["seconds_until_closed"] = round(inc.closed_at - inc.created_at, 1)
        self.store.save_incident(inc)
        self.store.audit(iid, "incident_" + rep["status"], {"invariants": rep["invariants"],
                                                            "blocked_reason": rep["closure_blocked_reason"]})
        if inc.ticket and rep["status"] in (IS.closed_verified.value, IS.escalated.value):
            try:
                self.sb.pm.comment(inc.ticket, rep["summary"], f"{iid}:comment:{rep['status']}")
                self.sb.pm.set_status(inc.ticket, "done" if rep["status"] == IS.closed_verified.value else "escalated",
                                      f"{iid}:status:{rep['status']}")
                self.store.audit(iid, "ticket_updated", {"ticket": inc.ticket, "status": rep["status"]})
            except (Transient, Timeout, Permanent) as e:
                self.store.audit(iid, "ticket_update_failed", {"error": type(e).__name__})
        rep["incident"] = inc.model_dump(mode="json")
        return rep


def follow_ups(inc, acts):
    """Work Rook deliberately leaves to a person, so nothing is silently dropped."""
    out = []
    for r in inc.relationships:
        if r["rel"] == "ownerless_account":
            out.append(f"Assign an owner to, or remove, the ownerless {r['service']} account '{r['user']}'.")
    if any(a.type == "scrub_exposed_secret" and a.status == S.verified for a in acts):
        paths = [a.target for a in acts if a.type == "scrub_exposed_secret"]
        out.append(f"Git history of {', '.join(paths)} still contains the revoked key. It no longer works; "
                   "rewrite history only if policy requires it.")
    for a in acts:
        if a.result.get("rolled_back"):
            out.append(f"{a.target} was rolled back to the previous key after its update failed. Fix the service, "
                       "then run the incident again.")
    return out


def evidence_pack(rep, audit, chain):
    """Markdown evidence for auditors: what happened, who approved, what was verified, and integrity."""
    inc = rep["incident"]
    L = [f"# Incident evidence: {inc['id']}", "",
         f"- Title: {inc['title']}", f"- Status: **{rep['status']}**", f"- Organisation: {inc['org']}",
         f"- Opened by: {inc['created_by']}", f"- Tracking ticket: {inc.get('ticket') or 'none'}",
         f"- Old key dead after: {rep['metrics']['seconds_until_old_key_dead']} s",
         f"- Closed after: {rep['metrics']['seconds_until_closed']} s", "",
         "## Summary", rep["summary"], "", "## Findings"]
    L += [f"- [{f['severity']}] {f['text']}" for f in inc["findings"]]
    L += ["", "## Actions", "| # | Action | Target | Status | Attempts | Policy |", "|---|---|---|---|---|---|"]
    L += [f"| {i+1} | {a['type']} | {a['target']} | {a['status']} | {a['retries'] + 1} | {a['policy'].get('rule')} |"
          for i, a in enumerate(rep["actions"])]
    L += ["", "## Approvals"] + ([f"- {x['decision']} by {x['by']} ({x['action']})" for x in rep["approvals"]] or ["- none"])
    L += ["", "## Closure checks (independently observed)", "| Check | Result | Evidence |", "|---|---|---|"]
    L += [f"| {c['description']} | {'PASS' if c['result'] else 'FAIL' if c['result'] is False else 'INCONCLUSIVE'} | "
          f"`{json.dumps(c['evidence'])}` |" for c in rep["conditions"]]
    L += ["", "## Invariants"] + [f"- {k}: {'yes' if v else 'no'}" for k, v in rep["invariants"].items()]
    L += ["", "## Follow-ups for a person"] + ([f"- {x}" for x in rep["follow_ups"]] or ["- none"])
    L += ["", "## Audit integrity",
          f"Hash chain over {chain[2]} audit events: {'intact' if chain[0] else f'BROKEN at event {chain[1]}'}.",
          f"Last event hash for this incident: `{audit[-1]['hash'] if audit else 'n/a'}`", "",
          "## Timeline"]
    L += [f"- {time.strftime('%H:%M:%S', time.gmtime(e['ts']))}Z {e['event']}" for e in audit]
    L += ["", "_Sandboxed mock integrations, synthetic credentials only._"]
    return "\n".join(L) + "\n"


def blocked_reason(inv, bad, unresolved):
    out = []
    if bad:
        out.append("checks not satisfied: " + ", ".join(bad))
    if unresolved:
        out.append("unfinished actions: " + ", ".join(f"{u['action']} {u['type']} ({u['status']})" for u in unresolved))
    failed = [k for k, v in inv.items() if not v]
    if not out and failed:
        out.append("failed invariants: " + ", ".join(failed))
    return "; ".join(out) or "not yet evaluated"


def summarize(inc, acts, status, bad):
    done = sum(a.status == S.verified for a in acts)
    if status == IS.closed_verified.value:
        return (f"Closed with evidence: all {len(acts)} actions were independently verified and every closure "
                "check passed. The old key is rejected, the replacement works, and every dependent is healthy.")
    if status == IS.awaiting_approval.value:
        waiting = [a for a in acts if a.status == S.needs_approval]
        return (f"{done} of {len(acts)} actions verified. Waiting for a person to approve: "
                + "; ".join(a.summary for a in waiting))
    if status == IS.escalated.value:
        probs = [f"{a.id} {a.type} on {a.target} is {a.status.value}" for a in acts if a.status in UNRESOLVED_BAD]
        return ("Escalated to a human: Rook could not finish safely and will not claim success. "
                + ("; ".join(probs) + ". " if probs else "")
                + (f"Failing checks: {', '.join(bad)}." if bad else ""))
    return f"{done} of {len(acts)} actions verified so far."
