"""Run one sandboxed incident end to end and print what happened.

    python -m rook.demo                       # offboarding: transient failure + recovery
    python -m rook.demo --scenario outage     # service outage: bad deploy, ambiguous rollback, recovery
    python -m rook.demo --scenario persistent # Rook escalates instead of claiming success
    NEATLOGS_API_KEY=... python -m rook.demo  # same, with traces exported to neatlogs

After each workflow step the demo probes the services the incident affects (the playbook decides
which), so a trace shows how long users were impacted and whether remediation made it worse.
"""
import argparse, json, os, tempfile, time
from . import obs
from .domain import Principal
from .engine import Engine
from .playbooks import playbook_for
from .sandbox import SCENARIOS, Sandbox
from .store import Store

# The demo plays the human approver from the command line. In the app, approval comes from an
# authenticated user with the approver role.
DEMO_APPROVER = Principal(id="demo-approver", org="acme", roles=["approver"], name="Demo approver")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="signature", choices=sorted(SCENARIOS))
    ap.add_argument("--no-approve", action="store_true", help="stop when approval is required")
    ap.add_argument("--label", default=os.getenv("ROOK_DEMO_LABEL", "dev"))
    args = ap.parse_args(argv)

    exporting = obs.init_neatlogs(workflow_name="rook-incident-response")
    db = os.path.join(tempfile.mkdtemp(), "demo.db")
    st = Store(db)
    sb = Sandbox(st, scenario=args.scenario)
    probes = {"steps": 0, "outage_steps": 0, "unhealthy": {}}
    pb = playbook_for(args.scenario)

    real_checkpoint = st.checkpoint

    def checkpoint(iid, label, data):        # probe dependents after every persisted step
        real_checkpoint(iid, label, data)
        if label != "step":
            return
        probes["steps"] += 1
        with obs.span("probe.dependent_health", incident=iid, step=probes["steps"]) as s:
            bad = pb.impact(sb, st.incident(iid))
            s.set(unhealthy_dependents=len(bad), healthy=not bad)
        if bad:
            probes["outage_steps"] += 1
            for a in bad:
                probes["unhealthy"][a] = probes["unhealthy"].get(a, 0) + 1
    st.checkpoint = checkpoint

    t0 = time.time()
    with obs.span("demo.incident", scenario=args.scenario, label=args.label) as root:
        eng = Engine(st, sb, sleep=lambda s: None)
        inc = eng.start(scenario=args.scenario)
        rep = eng.run(inc.id)
        if rep["status"] == "awaiting_approval" and not args.no_approve:
            for a in [x for x in st.actions(inc.id) if x.status.value == "needs_approval"]:
                eng.approve(inc.id, a.id, DEMO_APPROVER)
            rep = eng.run(inc.id)
        root.set(incident=inc.id, status=rep["status"], tool_calls=rep["metrics"]["tool_calls"],
                 dependent_outage_steps=probes["outage_steps"])
    summary = {
        "label": args.label, "scenario": args.scenario, "playbook": pb.key, "incident": inc.id,
        "status": rep["status"], rep["metrics"]["contain_label"].lower().replace(" ", "_") + "_s":
        rep["metrics"]["seconds_to_contain"],
        "duration_ms": round((time.time() - t0) * 1000, 1),
        "summary": rep["summary"],
        "tool_calls": rep["metrics"]["tool_calls"], "failed_tool_calls": rep["metrics"]["failed_tool_calls"],
        "checkpoints": rep["metrics"]["checkpoints"], "audit_events": rep["metrics"]["audit_events"],
        "conditions_passed": f"{sum(c['result'] is True for c in rep['conditions'])}/{len(rep['conditions'])}",
        "workflow_steps": probes["steps"], "dependent_outage_steps": probes["outage_steps"],
        "follow_ups": rep["follow_ups"],
        "unhealthy_dependents": probes["unhealthy"],
        "retries": {a["id"]: a["retries"] for a in rep["actions"] if a["retries"]},
        "neatlogs_export": exporting,
    }
    if exporting:
        obs.flush()
        summary["neatlogs_delivery"] = {k: v for k, v in obs.delivery().items()
                                        if k.startswith("span_") and isinstance(v, int)}
        obs.shutdown()
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
