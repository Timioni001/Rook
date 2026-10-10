"""Run one sandboxed incident end to end and print what happened.

    python -m rook.demo                       # signature scenario (transient failure + recovery)
    NEATLOGS_API_KEY=... python -m rook.demo  # same, with traces exported to neatlogs

The demo also probes every dependent application's health after each workflow step, so a trace
shows whether remediation caused an outage for the services that rely on the credential.
"""
import argparse, json, os, tempfile, time
from . import obs
from .engine import Engine
from .sandbox import Sandbox
from .store import Store

SCENARIOS = {
    "transient": ({"app.repair": ["transient"]}, {}),
    "clean": ({}, {}),
    "ambiguous": ({"vault.rotate": ["timeout_applied"]}, {}),
    "persistent": ({"app.repair": ["transient"] * 10}, {}),
}


def dependents(sb):
    return sorted({app for c in sb.vault.creds().values() for app in c["used_by"]})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="transient", choices=sorted(SCENARIOS))
    ap.add_argument("--label", default=os.getenv("ROOK_DEMO_LABEL", "dev"))
    args = ap.parse_args(argv)

    exporting = obs.init_neatlogs(workflow_name="rook-incident-response")
    db = os.path.join(tempfile.mkdtemp(), "demo.db")
    st = Store(db)
    failures, flags = SCENARIOS[args.scenario]
    sb = Sandbox(st, failures=failures, flags=flags)
    probes = {"steps": 0, "outage_steps": 0, "unhealthy": {}}

    real_checkpoint = st.checkpoint

    def checkpoint(iid, label, data):        # probe dependents after every persisted step
        real_checkpoint(iid, label, data)
        if label != "step":
            return
        probes["steps"] += 1
        with obs.span("probe.dependent_health", incident=iid, step=probes["steps"]) as s:
            bad = [a for a in dependents(sb) if not sb.apps.health(a)]
            s.set(unhealthy_dependents=len(bad), healthy=not bad)
        if bad:
            probes["outage_steps"] += 1
            for a in bad:
                probes["unhealthy"][a] = probes["unhealthy"].get(a, 0) + 1
    st.checkpoint = checkpoint

    t0 = time.time()
    with obs.span("demo.incident", scenario=args.scenario, label=args.label) as root:
        eng = Engine(st, sb, sleep=lambda s: None)
        inc = eng.start("ident-jdoe")
        rep = eng.run(inc.id)
        root.set(incident=inc.id, status=rep["status"], tool_calls=rep["metrics"]["tool_calls"],
                 dependent_outage_steps=probes["outage_steps"])
    summary = {
        "label": args.label, "scenario": args.scenario, "incident": inc.id, "status": rep["status"],
        "duration_ms": round((time.time() - t0) * 1000, 1),
        "tool_calls": rep["metrics"]["tool_calls"], "audit_events": rep["metrics"]["audit_events"],
        "workflow_steps": probes["steps"], "dependent_outage_steps": probes["outage_steps"],
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
