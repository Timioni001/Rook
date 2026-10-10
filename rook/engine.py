import json, os, time, uuid
from .domain import Action, Incident, Status, fp
from .sandbox import Transient, Permanent, Timeout
from . import policy
from .verification import build_conditions, evaluate, verify_action
from .obs import span

S = Status
RUNNABLE = {S.authorized, S.retry_pending, S.executing, S.executed, S.unknown}
ESCALATE = {S.failed, S.unknown, S.retry_pending, S.authorized, S.executing, S.executed}


class SimulatedCrash(BaseException):      # BaseException so no handler swallows it
    ...


def make_action(iid, n, type, target, params):
    return Action(id=f"{iid}-a{n}", incident_id=iid, type=type, target=target, params=params,
                  idem_key=f"{iid}:{type}:{params.get('service','')}:{target}")


def discover(sb, subject):
    """Observed access graph. Fingerprints and paths only; no secret values."""
    rel = []
    for name in ("github", "cloud", "pm"):
        for u, acc in sb.account_service(name).accounts().items():
            if acc["owner"] == subject:
                rel.append({"rel": "has_account", "service": name, "user": u, "status": acc["status"]})
    for cid, c in sb.vault.creds().items():
        if c["owner"] == subject:
            rel.append({"rel": "owns_credential", "cred": cid, "status": c["status"],
                        "fp": fp(c["value"]), "used_by": list(c["used_by"]),
                        "exposed_in": sb.github.find_secret(c["value"])})
    return rel


def explain(subject, rel):
    dis = [f"{r['service']}:{r['user']}" for r in rel if r["rel"] == "has_account" and r["status"] == "disabled"]
    act = [f"{r['service']}:{r['user']}" for r in rel if r["rel"] == "has_account" and r["status"] == "active"]
    parts = [f"{subject} is disabled on {', '.join(dis) or 'no services'} but still active on {', '.join(act) or 'no services'}."]
    for r in rel:
        if r["rel"] == "owns_credential" and r["status"] == "active":
            s = f"Credential {r['cred']} ({r['fp']}) is still active and used by {', '.join(r['used_by'])}."
            if r["exposed_in"]:
                s += f" It is exposed in {', '.join(r['exposed_in'])}."
            parts.append(s)
    return " ".join(parts)


class RuleBasedPlanner:
    def plan(self, obs, iid):
        acts = []

        def add(t, target, **p):
            acts.append(make_action(iid, len(acts) + 1, t, target, p))
        for r in obs:
            if r["rel"] == "has_account" and r["status"] == "active":
                add("disable_account", r["user"], service=r["service"])
        for r in obs:
            if r["rel"] == "owns_credential" and r["status"] == "active":
                add("rotate_credential", r["cred"], service="vault", old_fp=r["fp"])
                for app in r["used_by"]:
                    add("repair_config", app, service="app", cred_id=r["cred"], old_fp=r["fp"])
        return acts


class LLMPlanner:
    """Model proposes from fingerprint-only observations; policy still decides."""
    def __init__(self):
        self.fallback = RuleBasedPlanner()

    def plan(self, obs, iid):
        try:
            import anthropic
            m = anthropic.Anthropic().messages.create(
                model="claude-sonnet-5-5", max_tokens=1000,
                system=("Return ONLY a JSON list of {type,target,params}. Types: disable_account "
                        "(params.service in github|cloud|pm), rotate_credential (params.service='vault'), "
                        "repair_config (params.service='app', params.cred_id). Secrets are fingerprints."),
                messages=[{"role": "user", "content": json.dumps(obs)}])
            raw = json.loads(m.content[0].text)
            acts = [make_action(iid, i + 1, x["type"], x["target"], x.get("params", {}))
                    for i, x in enumerate(raw)
                    if x.get("type") in policy.ALLOWED]
            return acts or self.fallback.plan(obs, iid)
        except Exception:
            return self.fallback.plan(obs, iid)


class Engine:
    def __init__(self, store, sb, planner=None, max_steps=50, max_retries=3,
                 sleep=time.sleep, crash_after=None, step_delay=0.0):
        self.store, self.sb = store, sb
        self.planner = planner or (LLMPlanner() if os.getenv("ROOK_PLANNER") == "llm" else RuleBasedPlanner())
        self.max_steps, self.max_retries = max_steps, max_retries
        self.sleep, self.crash_after, self.step_delay = sleep, crash_after, step_delay
        self.executions = 0
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    # ---- OBSERVE -> DEFINE CLOSURE -> PLAN -> AUTHORIZE ----
    def start(self, subject, extra_actions=()):
        iid = "inc-" + uuid.uuid4().hex[:6]
        with span("incident.start", incident=iid, subject=subject):
            inc = Incident(id=iid, subject=subject)
            inc.relationships = discover(self.sb, subject)
            inc.exposure = explain(subject, inc.relationships)
            self.store.save_incident(inc)
            self.store.audit(iid, "observed", {"relationships": inc.relationships, "exposure": inc.exposure})

            conds = build_conditions(inc.relationships)       # defined BEFORE any remediation
            self.store.save_conditions(iid, conds)
            self.store.audit(iid, "closure_conditions_defined", {"conditions": [c.id for c in conds]})

            with span("plan", incident=iid):
                plan = self.planner.plan(inc.relationships, iid) + list(extra_actions)
            fps = {r["cred"]: r["fp"] for r in inc.relationships if r["rel"] == "owns_credential"}
            seen = set()
            for i, a in enumerate(plan):
                a.id, a.incident_id = f"{iid}-a{i+1}", iid
                a.idem_key = f"{iid}:{a.type}:{a.params.get('service','')}:{a.target}"
                a.max_retries = self.max_retries
                cred = a.target if a.type == "rotate_credential" else a.params.get("cred_id")
                if cred in fps:                              # observed truth overrides model input
                    a.params["old_fp"] = fps[cred]

            for i, a in enumerate(plan):
                with span("policy.decide", action=a.id, type=a.type, target=a.target):
                    if a.idem_key in seen:
                        decision, reason = "blocked", "duplicate/conflicting action"
                    else:
                        decision, reason = policy.decide(a, inc, self.sb, plan)
                seen.add(a.idem_key)
                a.policy = {"decision": decision, "reason": reason}
                a.move({"authorized": S.authorized, "needs_approval": S.needs_approval}.get(decision, S.blocked))
                self.store.add_action(a, i)
                self.store.audit(iid, "policy_" + decision, {"action": a.id, "type": a.type,
                                                             "target": a.target, "reason": reason})
                if decision == "blocked":
                    self.store.audit(iid, "escalated", {"action": a.id, "reason": reason})
            self.store.checkpoint(iid, "planned", {"actions": [a.id for a in plan]})
        return inc

    # ---- human approval (deterministic policy still re-checked) ----
    def approve(self, iid, action_id, approver="human"):
        a = next((x for x in self.store.actions(iid) if x.id == action_id), None)
        if a is None:
            raise KeyError(action_id)
        if a.status != S.needs_approval:
            raise ValueError(f"{action_id} is {a.status.value}, not awaiting approval")
        decision, reason = policy.decide(a, self.store.incident(iid), self.sb,
                                         self.store.actions(iid), approved=True)
        if decision == "authorized":
            a.move(S.authorized)
            a.policy = {"decision": "authorized", "reason": reason, "approved_by": approver}
            self.store.audit(iid, "approval_granted", {"action": a.id, "by": approver})
        else:
            a.move(S.blocked)
            a.policy = {"decision": "blocked", "reason": reason}
            self.store.audit(iid, "approval_rejected_by_policy", {"action": a.id, "reason": reason})
        self.store.save_action(a)
        return a

    # ---- EXECUTE -> VERIFY -> CHECKPOINT -> CONTINUE OR RECOVER (resumable from the DB) ----
    def run(self, iid):
        steps = 0
        with span("incident.run", incident=iid):
            for a in self.store.actions(iid):
                while a.status in RUNNABLE and steps < self.max_steps and not self.cancelled:
                    steps += 1
                    halt = self._step(a)
                    self.store.save_action(a)
                    self.store.checkpoint(iid, "step", {"action": a.id, "status": a.status.value})
                    if self.step_delay:
                        time.sleep(self.step_delay)
                    if halt:
                        break
                if a.status in ESCALATE:
                    self.store.audit(iid, "escalated", {"action": a.id, "status": a.status.value,
                                                        "reason": "unresolved, failed, or budget exhausted"})
            if self.cancelled:
                self.store.audit(iid, "cancelled", {})
            return self.finalize(iid)

    def _precondition(self, a):
        if a.type != "repair_config":
            return True
        rot = [x for x in self.store.actions(a.incident_id)
               if x.type == "rotate_credential" and x.target == a.params["cred_id"]]
        return bool(rot) and all(x.status == S.verified for x in rot)

    def _step(self, a):
        iid = a.incident_id
        if a.status in (S.executing, S.unknown):
            # outcome uncertain: inspect real state BEFORE any new mutation
            with span("reconcile", action=a.id):
                ok, ev = verify_action(self.sb, a)
            a.evidence = ev
            if ok is True:
                a.move(S.verified)
                self.store.audit(iid, "reconciled_verified", {"action": a.id, "evidence": ev})
            elif ok is False:
                a.move(S.retry_pending)
                self.store.audit(iid, "reconciled_not_applied", {"action": a.id, "evidence": ev})
            else:
                a.move(S.unknown)
                self.store.audit(iid, "reconcile_inconclusive", {"action": a.id, "evidence": ev})
                return True
            return False

        if a.status in (S.authorized, S.retry_pending):
            if not self._precondition(a):
                self.store.audit(iid, "precondition_unmet", {"action": a.id,
                                 "reason": "credential rotation not verified"})
                return True
            a.move(S.executing)
            self.store.save_action(a)
            self.store.audit(iid, "executing", {"action": a.id, "attempt": a.retries + 1})
            try:
                with span("execute", action=a.id, type=a.type, target=a.target):
                    a.result = self._exec(a)
                self.executions += 1
                if self.crash_after is not None and self.executions >= self.crash_after:
                    raise SimulatedCrash()    # after mutation, before status is persisted
                a.move(S.executed)
                self.store.audit(iid, "executed", {"action": a.id, "result": a.result})
            except Transient as e:
                a.retries += 1
                a.result = {"error": str(e)}
                if a.retries > a.max_retries:
                    a.move(S.failed)
                    self.store.audit(iid, "failed_retries_exhausted", {"action": a.id})
                else:
                    a.move(S.retry_pending)
                    self.store.audit(iid, "transient_failure_retry", {"action": a.id, "retries": a.retries})
                    self.sleep(0.05 * 2 ** a.retries)
            except Permanent as e:
                a.move(S.failed)
                a.result = {"error": str(e)}
                self.store.audit(iid, "permanent_failure", {"action": a.id, "error": str(e)})
            except Timeout as e:
                a.move(S.unknown)
                a.result = {"error": f"timeout: {e}"}
                self.store.audit(iid, "timeout_unknown_outcome", {"action": a.id})
            except Exception as e:
                a.move(S.failed)
                a.result = {"error": type(e).__name__}
                self.store.audit(iid, "unexpected_failure", {"action": a.id, "error": type(e).__name__})
            return False

        if a.status == S.executed:
            with span("verify", action=a.id):
                ok, ev = verify_action(self.sb, a)
            a.evidence = ev
            if ok is True:
                a.move(S.verified)
            elif ok is False:
                a.move(S.failed)
                a.result = {**a.result, "error": "executed but independent verification failed"}
            else:
                a.move(S.unknown)
            self.store.audit(iid, "verification_" + a.status.value, {"action": a.id, "evidence": ev})
        return False

    def _exec(self, a):
        p = a.params
        if a.type == "disable_account":
            return self.sb.account_service(p["service"]).disable(a.target, a.idem_key)
        if a.type == "rotate_credential":
            return self.sb.vault.rotate(a.target, a.idem_key)
        if a.type == "repair_config":
            return self.sb.apps.repair_config(a.target, p["cred_id"], a.idem_key)
        raise Permanent("unsupported action")

    # ---- Verified Closure: live re-observation against pre-defined conditions ----
    def report(self, iid):
        inc = self.store.incident(iid)
        acts = self.store.actions(iid)
        stored = self.store.conditions(iid)
        conds = evaluate(self.sb, stored)
        mandatory = [c for c in conds if c.mandatory]
        inv = {
            "closure_conditions_defined": bool(stored),
            "no_inconclusive_conditions": bool(stored) and all(c.result is not None for c in mandatory),
            "all_mandatory_conditions_pass": bool(stored) and all(c.result is True for c in mandatory),
            "all_actions_verified": all(a.status == S.verified for a in acts),
        }
        closed = all(inv.values())
        bad = [c.id for c in conds if c.mandatory and c.result is not True]
        return {
            "incident": inc.model_dump(mode="json"),
            "status": "closed_verified" if closed else "open",
            "exposure": inc.exposure,
            "invariants": inv,
            "conditions": [c.model_dump(mode="json") for c in conds],
            "actions": [{"id": a.id, "type": a.type, "target": a.target, "status": a.status.value,
                         "retries": a.retries, "policy": a.policy, "result": a.result,
                         "evidence": a.evidence} for a in acts],
            "unresolved": [{"action": a.id, "type": a.type, "target": a.target, "status": a.status.value,
                            "reason": a.policy.get("reason") if a.status in (S.blocked, S.needs_approval)
                            else a.result.get("error", "not verified")}
                           for a in acts if a.status != S.verified],
            "closure_blocked_reason": None if closed else
                "failed invariants: " + (", ".join(k for k, v in inv.items() if not v) or "none")
                + ("; conditions not satisfied: " + ", ".join(bad) if bad else ""),
            "metrics": {"tool_calls": self.sb.s["calls"], "rotations": self.sb.s["rotations"],
                        "audit_events": len(self.store.audit_events(iid))},
        }

    def finalize(self, iid):
        with span("closure.evaluate", incident=iid):
            rep = self.report(iid)
        self.store.save_conditions(iid, [type(c)(**c) if False else _cond(c) for c in rep["conditions"]])
        inc = self.store.incident(iid)
        inc.status = rep["status"]
        self.store.save_incident(inc)
        self.store.audit(iid, "incident_" + rep["status"], {"invariants": rep["invariants"]})
        return rep


def _cond(d):
    from .domain import Condition
    return Condition(**d)
