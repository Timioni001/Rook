#!/usr/bin/env python3
"""Prove a live Rook deployment works, end to end, from outside it.

    python3 scripts/check-live.py https://rook.pages.dev
    python3 scripts/check-live.py https://rook.onrender.com --scenario signature

It wakes the agent if it is asleep, loads the dashboard, then runs a real incident
through to Verified Closure and prints how long each part took. Run it before judging
or before recording the video. Exit status is 0 only if the incident closed verified.

Only the built-in demo identities are used, so this works against any deployment that
still has ROOK_DEMO_TOKENS on. Nothing it does leaves the synthetic sandbox.
"""
import argparse, json, sys, time, urllib.error, urllib.request

ANALYST = "demo-analyst-token"
APPROVER = "demo-approver-token"


def call(base, path, token=None, body=None, timeout=120):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip().startswith((b"{", b"[")) else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:                       # connection refused, DNS, TLS, timeout
        return 0, str(e)


def step(name):
    print(f"  {name:.<46}", end="", flush=True)


def ok(detail=""):
    print(f" ok {detail}")


def fail(detail):
    print(f" FAILED {detail}")


def wake(base, budget):
    """A sleeping free instance refuses or 5xxs until it has started. Wait it out."""
    started = time.time()
    while time.time() - started < budget:
        status, body = call(base, "/api/health", timeout=90)
        if status == 200 and isinstance(body, dict) and body.get("ok"):
            return round(time.time() - started, 1), None
        time.sleep(3)
    return None, f"no healthy answer within {budget}s (last: {status} {body})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="the public address, e.g. https://rook.pages.dev")
    ap.add_argument("--scenario", default="outage", help="sandbox scenario (default: outage)")
    ap.add_argument("--wake-budget", type=int, default=180, help="seconds to allow for a cold start")
    ap.add_argument("--run-budget", type=int, default=240, help="seconds to allow for the incident")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    print(f"Checking {base}\n")

    step("agent reachable")
    secs, err = wake(base, a.wake_budget)
    if err:
        fail(err)
        return 1
    ok(f"(woke in {secs}s)" if secs > 2 else "")

    step("dashboard served")
    status, body = call(base, "/")
    if status != 200:
        fail(f"GET / returned {status}")
        return 1
    ok()

    step("demo identity accepted")
    status, me = call(base, "/api/me", ANALYST)
    if status != 200:
        fail(f"/api/me returned {status} {me}. Demo tokens may be off on this deployment.")
        return 1
    ok(f"({me.get('name')})")

    step(f"start incident [{a.scenario}]")
    status, inc = call(base, "/api/incidents", ANALYST, {"scenario": a.scenario})
    if status == 409:
        fail(f"{inc}. Wait for the running incident to finish, then try again.")
        return 1
    if status != 201:
        fail(f"POST /api/incidents returned {status} {inc}")
        return 1
    iid = inc["id"]
    ok(iid)

    step("run plan")
    status, _ = call(base, f"/api/incidents/{iid}/run", ANALYST, {})
    if status != 202:
        fail(f"run returned {status}")
        return 1
    ok()

    started, approved, state = time.time(), False, "?"
    while time.time() - started < a.run_budget:
        status, d = call(base, f"/api/incidents/{iid}", ANALYST)
        if status != 200:
            fail(f"polling returned {status}")
            return 1
        state = d["report"]["incident"]["status"]
        if state == "awaiting_approval" and not approved:
            pending = [x for x in d["report"]["actions"] if x["status"] == "needs_approval"]
            if pending:
                step(f"approve {pending[0]['type']}")
                status, _ = call(base, f"/api/incidents/{iid}/actions/{pending[0]['id']}/approve", APPROVER, {})
                if status != 200:
                    fail(f"approval returned {status}")
                    return 1
                approved = True
                ok("(as Priya)")
                continue
        if state in ("closed_verified", "escalated") and not d["running"]:
            break
        time.sleep(2)

    status, d = call(base, f"/api/incidents/{iid}", ANALYST)
    r = d["report"]
    conds = r["conditions"]
    passing = sum(1 for c in conds if c.get("result") is True)
    verified = sum(1 for x in r["actions"] if x["status"] == "verified")

    step("closure checks")
    print(f" {passing}/{len(conds)} passing")
    step("actions verified")
    print(f" {verified}/{len(r['actions'])}")

    step("evidence pack")
    status, md = call(base, f"/api/incidents/{iid}/evidence", ANALYST)
    ok(f"({len(md)} bytes)") if status == 200 else fail(f"returned {status}")

    took = round(time.time() - started, 1)
    print()
    if r["incident"]["status"] == "closed_verified" and passing == len(conds):
        print(f"PASS  {iid} closed verified in {took}s. This deployment is ready to demo.")
        return 0
    if a.scenario in ("outage_wrong_cause", "persistent", "outage_rollback_down") and r["incident"]["status"] == "escalated":
        print(f"PASS  {iid} escalated in {took}s, which is what [{a.scenario}] is meant to do.")
        return 0
    print(f"FAIL  {iid} ended as {r['incident']['status']} after {took}s, {passing}/{len(conds)} checks passing.")
    for c in conds:
        if c.get("result") is not True:
            print("      unmet:", c.get("description") or c)
    return 1


if __name__ == "__main__":
    sys.exit(main())
